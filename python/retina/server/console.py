"""Python console of the web shell — IPython's ``InteractiveShell``, **in the same process**.

This is the "console completeness" pillar of ARCHITECTURE.md: the console manipulates *the
same objects* as the interface, not a serialized copy. An ``app.active_view`` typed here is
exactly the object the viewport displays.

# Why InteractiveShell and not ipykernel

A real Jupyter kernel would pull in pyzmq, jupyter_client and tornado, impose its event-loop
integration, and force us to speak the Jupyter protocol in TypeScript. We need none of its
distinguishing features (multi-client, remote rich display): ``InteractiveShell`` gives
completion, persistent history, magics and formatted tracebacks, in one import.

# Threads

Execution lives on **one** dedicated thread, never on the asyncio loop. Two reasons: a long
script (a stack of 50 exposures) would otherwise leave the interface without progress or
echo; and a single thread naturally serializes runs, which avoids two concurrent scripts on
the same ``app``.

Standard output is redirected by a **thread-aware** proxy: redirecting ``sys.stdout``
globally would also steal the server's logs, which run on the loop.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..paths import config_dir

if TYPE_CHECKING:
    from ..app import Application

log = logging.getLogger("retina.server")

#: Beyond this, we flush the buffer without waiting for the end of line — a loop writing
#: without a carriage return must not give the impression that nothing is happening.
_FLUSH_THRESHOLD = 4096


def _history_path() -> Path:
    """IPython history filed with the rest of the Retina config, not in ``~/.ipython``."""
    root = config_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / "console-history.sqlite"


class _ThreadStreamProxy:
    """Replaces ``sys.stdout``/``sys.stderr``, intercepting a single thread only.

    Without that filtering, everything the server logs while a script runs would go into the
    console transcript instead of the terminal.
    """

    def __init__(self, original, owner: threading.Thread, emit: Callable[[str], None]) -> None:
        self._original = original
        self._owner = owner
        self._emit = emit
        self._buffer: list[str] = []
        self._size = 0

    def write(self, text: str) -> int:
        if threading.current_thread() is not self._owner:
            return self._original.write(text)
        self._buffer.append(text)
        self._size += len(text)
        if "\n" in text or self._size >= _FLUSH_THRESHOLD:
            self.flush()
        return len(text)

    def flush(self) -> None:
        if threading.current_thread() is not self._owner:
            self._original.flush()
            return
        if self._buffer:
            payload = "".join(self._buffer)
            self._buffer.clear()
            self._size = 0
            self._emit(payload)

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class Console:
    """Embedded IPython shell, driven from the WebSocket."""

    def __init__(
        self,
        app: Application,
        on_stream: Callable[[str, str], None],
    ) -> None:
        self._app = app
        self._on_stream = on_stream
        self._shell: Any = None
        self._thread_id: int | None = None
        # a single worker: runs are serialized, as in a real REPL
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="retina-console")

    # --- lazy construction ----------------------------------------------------
    def _ensure_shell(self) -> Any:
        """Create the shell on first use — importing IPython costs ~0.5 s that we do not
        impose on a server whose console may never be opened."""
        if self._shell is not None:
            return self._shell

        from IPython.core.interactiveshell import InteractiveShell
        from traitlets.config import Config

        config = Config()
        config.HistoryManager.hist_file = str(_history_path())
        # Tracebacks without ANSI sequences: the transcript is DOM, not a terminal.
        config.InteractiveShell.colors = "nocolor"

        # `instance()` and not the constructor, and that is not a detail: creating a shell
        # installs `__IPYTHON__` in the builtins, and several libraries use it as a "we are
        # running under IPython" flag before calling `get_ipython()`. Astropy does
        # (astropy/logger.py) and crashed on a `None` as long as the shell was not registered
        # as the instance. The shell is therefore, in effect, a process resource —
        # registering it is the only way for the two signals to agree.
        #
        # Consequence: a second Console in the same process finds that namespace again. In
        # production there is only one server; we reinject `app` below so that it is always
        # THIS server's.
        shell = InteractiveShell.instance(config=config)
        shell.colors = "nocolor"

        # Jedi does **static** inference: on a namespace populated with live objects (`app`,
        # the views, the process instances), it returns nothing — measured, zero completions
        # on `app.zoom_`. IPython's dynamic completer, which queries the real objects,
        # proposes the four expected methods. That is precisely the use case of a console
        # attached to live state.
        shell.Completer.use_jedi = False

        # IPython's tracebacks go to **stdout**: `_showtraceback` does a plain `print(val)`.
        # In a terminal that goes unnoticed; in our transcript, where the color comes from
        # the stream name, an error was displayed in the same color as an ordinary
        # `print()` — a failing script looked as if it had succeeded. The method's docstring
        # itself announces the override as an intended extension point.
        def _show_traceback(etype, evalue, stb, _shell=shell) -> None:
            print(_shell.InteractiveTB.stb2text(stb), file=sys.stderr)

        shell._showtraceback = _show_traceback

        # Mute displayhook: it computes everything, but prints nothing.
        #
        # IPython itself writes ``Out[3]: 42`` on stdout. That stream being captured and
        # rendered as standard output, the result was displayed **twice** — as raw text, then
        # in the typed block the client builds from ``repr``. Only the three writing methods
        # are neutralized: ``update_user_ns`` keeps populating ``_``, ``_3`` and ``Out``, and
        # ``fill_exec_result`` keeps filling ``ExecutionResult.result``, from which that
        # ``repr`` is drawn. Patched on the instance, like ``_showtraceback`` above: the
        # ``displayhook_class`` trait is not picked up from the ``Config`` (verified).
        shell.displayhook.write_output_prompt = lambda: None
        shell.displayhook.write_format_data = lambda format_dict, md_dict=None: None
        shell.displayhook.finish_displayhook = lambda: None

        import retina

        shell.user_ns.update({"app": self._app, "retina": retina})
        shell.banner1 = ""
        self._shell = shell
        return shell

    # --- execution ------------------------------------------------------------
    def execute(self, code: str) -> dict:
        """Run a cell. **Called from the console thread**, never from the loop."""
        shell = self._ensure_shell()
        self._thread_id = threading.get_ident()
        # A cell's number is the one it bears **during** its execution: read after
        # `run_cell`, `execution_count` has already advanced, and the transcript displayed
        # `Out[4]` for what IPython had just named `Out[3]`.
        count = shell.execution_count

        owner = threading.current_thread()
        stdout = _ThreadStreamProxy(sys.stdout, owner, lambda t: self._on_stream("stdout", t))
        stderr = _ThreadStreamProxy(sys.stderr, owner, lambda t: self._on_stream("stderr", t))
        saved = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = stdout, stderr
        try:
            result = shell.run_cell(code, store_history=True)
        except KeyboardInterrupt:
            # interruption landed between two statements: the script really is stopped
            return {"execution_count": count, "status": "interrupted"}
        finally:
            stdout.flush()
            stderr.flush()
            sys.stdout, sys.stderr = saved
            self._thread_id = None

        error = result.error_in_exec or result.error_before_exec
        return {
            "execution_count": count,
            "status": "ok" if result.success else "error",
            "error": None if error is None else f"{type(error).__name__}: {error}",
            # `repr` of the last expression, when it produced one
            "repr": None if result.result is None else repr(result.result),
        }

    def interrupt(self) -> bool:
        """Raise ``KeyboardInterrupt`` in the console thread (the equivalent of a Ctrl+C).

        Same mechanism and same limits as a terminal IPython: the exception is raised between
        two bytecodes, so a call blocked in native code (numpy, scipy) only interrupts on its
        return.
        """
        thread_id = self._thread_id
        if thread_id is None:
            return False
        count = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(thread_id), ctypes.py_object(KeyboardInterrupt)
        )
        if count > 1:  # pragma: no cover — should never happen with a valid id
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread_id), None)
            return False
        return count == 1

    # --- introspection --------------------------------------------------------
    def complete(self, code: str, cursor_pos: int | None = None) -> dict:
        """Completions at the cursor position.

        Uses ``Completer.complete`` despite its "pending deprecation" warning: its announced
        replacement, ``completions()``, is marked *provisional* — "may change without
        notice". Trading an API deprecated since IPython 6.0 but still present in 9.x for an
        unstable one would be a bad deal.
        """
        shell = self._ensure_shell()
        position = len(code) if cursor_pos is None else cursor_pos
        text, matches = shell.Completer.complete(line_buffer=code, cursor_pos=position)
        return {
            "matches": list(matches),
            # The client replaces this interval with the chosen completion.
            "replace_start": position - len(text),
            "replace_end": position,
        }

    def inspect(self, code: str, cursor_pos: int | None = None) -> dict:
        """Documentation of the object under the cursor (IPython's `?`).

        Returns two levels of detail, because the editor puts them to two distinct uses:

        - ``text`` is IPython's pre-formatted block (Signature / Docstring / File / Type),
          displayed as is on hover. Re-cutting it into Markdown would be fragile for
          nothing — it is readable text, written to be read.
        - ``definition``/``init_definition``/``docstring`` come from ``object_inspect``, and
          serve the **signature** help, which needs the call line in isolation to underline
          the current parameter. A class files its call signature in ``init_definition``,
          never in ``definition`` — hence the two keys.

        These three keys are optional: an object without a signature (an integer, a module)
        carries none, and the caller must expect that.
        """
        shell = self._ensure_shell()
        position = len(code) if cursor_pos is None else cursor_pos
        name = _symbol_at(code, position)
        if not name:
            return {"found": False, "text": ""}
        try:
            info = shell.object_inspect_text(name)
        except Exception:
            return {"found": False, "text": ""}
        result: dict[str, Any] = {"found": bool(info), "text": info or ""}
        try:
            details = shell.object_inspect(name, detail_level=0)
        except Exception:
            return result
        for key in ("definition", "init_definition", "docstring"):
            value = details.get(key) if isinstance(details, dict) else None
            # IPython puts the `<no docstring>` sentinel rather than an absence: relaying it
            # would display a help bubble whose entire content is "no doc".
            if value and value != "<no docstring>":
                result[key] = value
        return result

    def history(self, limit: int = 100) -> list[str]:
        """Previous entries, the most recent last."""
        shell = self._ensure_shell()
        entries = list(shell.history_manager.get_tail(limit, include_latest=True))
        return [source for _session, _line, source in entries]

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


def _symbol_at(code: str, position: int) -> str:
    """Extract the (dotted) identifier surrounding the cursor position."""
    start = position
    while start > 0 and (code[start - 1].isalnum() or code[start - 1] in "._"):
        start -= 1
    end = position
    while end < len(code) and (code[end].isalnum() or code[end] in "._"):
        end += 1
    return code[start:end].strip(".")
