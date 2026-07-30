"""Process registry — discovery through Python entry points (the plugin model).

Processes declare themselves in the ``retina.processes`` entry-point group (see
pyproject.toml), on the napari plugin model: a third-party package can add processes without
modifying Retina. A fallback by direct import guarantees that the bundled processes are always
available, even without metadata (an uninstalled source tree, for instance).

To this is added a **user process directory** (``config_dir()/processes/*.py``,
:func:`load_user`): the plugin model without the packaging. That is where the built-in
assistant writes the processes it develops, and where a user drops a file by hand — reloaded
on every launch, everywhere ``load_builtin`` is called (shell, batch, pipeline, console), as
parity demands.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from ..i18n import translate as _t
from .base import Process

log = logging.getLogger("retina.process")

ENTRY_POINT_GROUP = "retina.processes"

_REGISTRY: dict[str, type[Process]] = {}
_LOADED = False

#: A single slot, set by the shell: notified on every ``register()``. This is what lets the
#: GUI catalog — requested only once per session — refresh itself when a process appears
#: along the way (console, assistant, ``load_user``).
on_changed: Callable[[], None] | None = None


def register(cls: type[Process]) -> type[Process]:
    """Decorator: register a process class under its ``process_id``."""
    _REGISTRY[cls.process_id] = cls
    if on_changed is not None:
        on_changed()
    return cls


def get(process_id: str) -> type[Process]:
    if process_id not in _REGISTRY:
        load_builtin()
    return _REGISTRY[process_id]


def all_processes() -> dict[str, type[Process]]:
    return dict(_REGISTRY)


def _discover_entry_points() -> int:
    """Load the processes declared through entry points. Returns the number discovered."""
    count = 0
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                obj = ep.load()
            except Exception:
                continue
            if isinstance(obj, type) and issubclass(obj, Process):
                register(obj)
                count += 1
            # if the entry point names a module, importing it already fired @register
    except Exception:
        pass
    return count


def load_builtin() -> None:
    """Make every process available: entry points + direct-import fallback (idempotent)."""
    global _LOADED
    _discover_entry_points()
    # safety net: guarantees the bundled processes even without install metadata
    from .. import processes  # noqa: F401  (the imports fire @register)

    # The user's processes last: they may deliberately replace a bundled process (same
    # ``process_id``), never the other way round.
    load_user()
    _LOADED = True


def user_process_dir() -> Path:
    """The user's process directory. Not created here — writing is what creates it."""
    from ..paths import config_dir

    return config_dir() / "processes"


def load_user(directory: Path | None = None) -> list[str]:
    """Load the ``*.py`` files of the user directory; return the list of failed files.

    Each file becomes a **real module** (registered in ``sys.modules``) and not a mere
    ``exec``: introspection and serialization of a ``ProcessInstance`` therefore find the
    class's source, just as for a bundled process.

    A broken file is logged and blocks neither its neighbors nor startup: a process being
    written — the assistant leaves drafts there — must never cost the application. Re-executing
    the module replaces the registry entry: this is what makes the "fix, reload" cycle possible
    without a restart.
    """
    import importlib.util
    import sys

    root = directory if directory is not None else user_process_dir()
    if not root.is_dir():
        return []

    failures: list[str] = []
    for path in sorted(root.glob("*.py")):
        module_name = f"retina_user_processes.{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(_t("Unreadable module spec: {path}").format(path=path))
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)  # the file's @register calls run here
        except Exception:
            sys.modules.pop(module_name, None)
            log.warning("user process ignored (%s)", path, exc_info=True)
            failures.append(str(path))
    return failures
