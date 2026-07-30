"""``library.*`` family — named instances and recipes, persisted to disk.

The library is the counterpart of "process icons": a configured instance you set aside,
rename, and drag onto a view. Storage is already handled by :mod:`retina.library` (one XML
file per entry, under ``RETINA_CONFIG_DIR``); this module is only its network facade.

As everywhere else, the handlers delegate to ``app.library``, which produces the Python echo.
Moving an icon on the desktop writes ``app.library.move('deconv', 120.0, 48.0)`` in the
console.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..process.container import ProcessContainer
from .rpc import DOMAIN_ERROR, RpcError

if TYPE_CHECKING:
    from ..app import Application

LIBRARY_METHODS: dict[str, bool] = {
    "library.list": False,
    "library.get": False,
    "library.put": False,
    "library.delete": False,
    "library.rename": False,
    "library.set_position": False,
}


class LibraryHandlers:
    def __init__(self, app: Application) -> None:
        self._app = app

    def list(self) -> list[dict]:
        """Library entries, with their position on the desktop.

        ``position`` is ``None`` as long as the entry has never been placed — it is up to the
        client to decide where to drop it, and to persist that if it does.
        """
        library = self._app.library
        entries = []
        for name in library.names():
            position = library.position(name)
            kind = library.kind(name)
            entry: dict[str, Any] = {
                "name": name,
                "kind": kind,
                "position": None if position is None else list(position),
            }
            try:
                item = library[name]
            except (KeyError, ValueError):
                continue  # unreadable entry: we skip it rather than break the whole list
            if kind == "container":
                entry["process_ids"] = [p.process_id for p in item.processes]
            else:
                entry["process_id"] = item.process_id
            entries.append(entry)
        return entries

    def get(self, name: str) -> dict:
        """Full contents of an entry — enough to reopen its pre-filled form."""
        library = self._app.library
        try:
            item = library[name]
        except KeyError:
            raise RpcError(DOMAIN_ERROR, f"unknown entry: {name!r}") from None

        if isinstance(item, ProcessContainer):
            # `to_dicts` and not a comprehension: the wire form of a recipe also carries the
            # disabled steps and their masks, which a round trip must not lose.
            return {"name": name, "kind": "container", "processes": item.to_dicts()}
        return {"name": name, "kind": "instance", "processes": [item.to_dict()]}

    def put(self, name: str, processes: list[dict]) -> None:
        """Saves an instance (one process) or a recipe (several)."""
        if not processes:
            raise RpcError(DOMAIN_ERROR, "no process to save")
        try:
            container = ProcessContainer.from_dicts(processes)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise RpcError(DOMAIN_ERROR, f"unreadable process: {exc}") from None
        # A single process stays an instance; beyond that it is a replayable recipe. A lone
        # process **carrying a flag** stays a recipe: demoting it to an instance would lose
        # its mask or its disabled state.
        lone = len(container) == 1 and container.enabled(0) and container.mask_id(0) is None
        self._app.library[name] = container.processes[0] if lone else container

    def delete(self, name: str) -> None:
        """Deletes an entry."""
        try:
            del self._app.library[name]
        except KeyError:
            raise RpcError(DOMAIN_ERROR, f"unknown entry: {name!r}") from None

    def rename(self, old: str, new: str) -> None:
        """Renames an entry (the name is the key, and the file name derives from it)."""
        try:
            self._app.library.rename(old, new)
        except (KeyError, ValueError) as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None

    def set_position(self, name: str, x: float, y: float) -> None:
        """Position of the icon on the desktop, persisted in the entry itself."""
        try:
            self._app.library.move(name, x, y)
        except KeyError:
            raise RpcError(DOMAIN_ERROR, f"unknown entry: {name!r}") from None
