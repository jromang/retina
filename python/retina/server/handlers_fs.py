"""``fs.*`` family — list a directory, read and write a text file.

# Why the server, and not the native shell

The tao/wry shell knows how to open a file dialog, and it would have been tempting to let it
read the bytes too. That is refused, and the reason is written at the top of
``crates/retina_shell/src/main.rs``: the shell returns **paths**, never content. Giving it
the content would create a capability the console would not have — the exact opposite of
pillar #2. In browser or remote mode, moreover, the disk that matters is the *server's*: that
is where ``app.open`` looks for images and where ``app.run_recipe`` runs scripts.

# What this family adds to the security model: nothing

The IPython console exposed by ``console.execute`` already gives any authenticated client
full access to the file system — ``open('/etc/passwd').read()`` is one line of Python. The
trust boundary is, and remains, :mod:`retina.server.security`: token + local origin. This
module does not widen the surface, it **types** it: three named operations, with clean
errors, instead of a generic ``exec``.

The guards that follow therefore target the accident, not the attacker: a relative path sent
by mistake would be resolved against the server's current directory, which makes no sense for
the client; a 2 GB binary file would drown the editor. Hence the requirement of absolute
paths and the read ceiling.

# Detecting an external modification: no watcher, a stamp

A script open in a tab can be modified by an external editor — the everyday gesture of anyone
who keeps Retina open and fixes their script in vim. With nothing in place, the next save
overwrites the external work **silently**, and a clean tab keeps displaying stale content.

The remedy is **not** a file system watcher (``watchdog``/``watchfiles``): one more
dependency, one more thread, events that differ across platforms and network mounts, and an
avalanche of notifications as soon as a folder of raw frames moves. The client therefore
queries the disk **at the only two instants that matter**: before writing, and when the tab
(or the window) comes back to the foreground. That is exactly the moment the user is looking,
at zero cost the rest of the time.

Hence the stamp returned by ``read_text``/``write_text`` and the ``stat`` method: the pair
**(size, mtime_ns)**, the same notion of file identity as
:mod:`retina.pipeline.file_cache` (``_identity``). The code is not imported from there: that
would pull the whole ``retina.pipeline`` package — and its heavy imports — into text file
transport, for two lines of ``os.stat``, around a private function whose contract (``None``
if unreadable) is not the one wanted here. Its limitations, on the other hand, are inherited
as is: this is not a hash, and a file system with low-resolution mtime can miss two writes
within the same second if the size is identical.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .rpc import DOMAIN_ERROR, RpcError

FS_METHODS: dict[str, bool] = {  # {RPC name: mutating}
    # None of these methods touches the domain: writing a script creates no window, modifies
    # no view, there is no snapshot to rebroadcast.
    "fs.home": False,
    "fs.list": False,
    "fs.read_text": False,
    "fs.write_text": False,
    "fs.stat": False,
}

#: Read ceiling. A Python script is a few tens of kilobytes; beyond that size, the target is
#: a file that has no business in an editor.
MAX_TEXT_BYTES = 2 * 1024 * 1024


def _resolve(path: str) -> Path:
    """Normalized absolute path, or :class:`RpcError`.

    ``expanduser`` first: ``~/scripts`` is an absolute path to a human, and the client has no
    way of knowing the server's home before having asked for it.
    """
    if not isinstance(path, str) or not path:
        raise RpcError(DOMAIN_ERROR, "path expected (non-empty string)")
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise RpcError(DOMAIN_ERROR, f"absolute path expected: {path!r}")
    return candidate.resolve()


def _stamp(target: Path) -> dict[str, Any]:
    """File stamp: ``{exists, size, mtime_ns}``.

    ``exists`` is false for anything that is not a readable ordinary file — a directory
    included. The client uses it to decide whether it can re-read, and re-reading a
    directory makes no sense.

    ``mtime_ns`` rather than ``mtime``: the latter's float in seconds is already rounded on
    the Python side, whereas the integer in nanoseconds carries everything the file system
    knows. The JavaScript client will round it to within ~256 ns (beyond 2^53), which is
    still a thousand times finer than any file system clock — and it only performs an
    equality comparison on it, never a computation.
    """
    try:
        info = target.stat()
    except OSError:
        return {"exists": False, "size": 0, "mtime_ns": 0}
    if not target.is_file():
        return {"exists": False, "size": 0, "mtime_ns": 0}
    return {"exists": True, "size": info.st_size, "mtime_ns": info.st_mtime_ns}


class FsHandlers:
    """File access on the *server*. Stateless: everything starts from the received path."""

    def home(self) -> str:
        """Home directory of the user running the server.

        Fallback root of the explorer: the client cannot guess it, and guessing it from the
        browser would give the wrong disk in remote mode.
        """
        return str(Path.home())

    def list(self, path: str | None = None, hidden: bool = False) -> dict:
        """Contents of a directory: subdirectories first, then files, in alphabetical order.

        ``parent`` is ``None`` at the root of the file system — that is what lets the client
        disable "go up" without knowing the platform's convention.
        """
        target = Path.home() if path is None else _resolve(path)
        if not target.is_dir():
            raise RpcError(DOMAIN_ERROR, f"directory not found: {target}")

        entries: list[dict[str, Any]] = []
        try:
            for item in os.scandir(target):
                if not hidden and item.name.startswith("."):
                    continue
                try:
                    is_dir = item.is_dir()
                    stat = item.stat()
                    size, mtime = stat.st_size, stat.st_mtime
                except OSError:
                    # Broken link or entry vanished during the walk: we skip it rather than
                    # lose the whole listing over one line.
                    continue
                entries.append(
                    {"name": item.name, "is_dir": is_dir, "size": size, "mtime": mtime}
                )
        except PermissionError:
            raise RpcError(DOMAIN_ERROR, f"unreadable directory: {target}") from None

        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        parent = target.parent
        return {
            "path": str(target),
            "parent": None if parent == target else str(parent),
            "entries": entries,
        }

    def stat(self, path: str) -> dict:
        """Stamp of a file, without reading it — ``{path, exists, size, mtime_ns}``.

        This is the "I am coming back to my tab" method: checking that a 100 kB file has not
        moved must not cost 100 kB over the WebSocket. A missing file is **not** an error
        here: it is an answer (``exists: false``), since the question asked is precisely
        "what is on the disk?".
        """
        target = _resolve(path)
        return {"path": str(target), **_stamp(target)}

    def read_text(self, path: str) -> dict:
        """Contents of a text file (UTF-8, invalid characters replaced) + stamp.

        The stamp is taken **after** the read: in between, a third party could have rewritten
        the file, and keeping the earlier stamp would make us believe forever that the buffer
        is up to date. Taken after, the worst case is a false divergence — we ask for one
        confirmation too many, never do we overwrite silently.
        """
        target = _resolve(path)
        if not target.is_file():
            raise RpcError(DOMAIN_ERROR, f"file not found: {target}")
        size = target.stat().st_size
        if size > MAX_TEXT_BYTES:
            raise RpcError(
                DOMAIN_ERROR,
                f"file too large ({size} bytes, maximum {MAX_TEXT_BYTES})",
            )
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise RpcError(DOMAIN_ERROR, f"cannot read: {exc}") from None
        return {"path": str(target), "text": text, **_stamp(target)}

    def write_text(self, path: str, text: str) -> dict:
        """Writes a text file. The parent directory must exist.

        Not creating the tree is deliberate: the path comes from a native dialog, which
        guarantees an existing parent. Creating it silently would turn a typo into a ghost
        directory.
        """
        target = _resolve(path)
        if not target.parent.is_dir():
            raise RpcError(DOMAIN_ERROR, f"nonexistent directory: {target.parent}")
        try:
            target.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise RpcError(DOMAIN_ERROR, f"cannot write: {exc}") from None
        # The stamp of what we have just written: this is what the client keeps as its
        # reference, without which the next check would immediately believe it divergent.
        return {"path": str(target), **_stamp(target)}
