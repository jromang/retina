"""Web backend of the ``app.layout`` API — implements the ``Protocol`` of :mod:`retina.layout`.

# Why a state mirror on the Python side

The thirteen methods of the ``Protocol`` are **synchronous**:
``app.layout.is_visible('console')`` typed in the console must return a ``bool`` right away.
Querying the frontend over the WebSocket would require a round trip — impossible to await
from a synchronous call without blocking the loop.

Hence the inversion: the panel state is held **here**, in memory. Reads are local and
immediate; writes update the mirror then push a command to the client. The client applies it
to dockview and sends back ``layout.report``, which reconciles the mirror with what the shell
actually did (dockview may group panels, or the user may close one with the mouse).

This is a cleaner model than a backend that would query the docking widget live: here the
console stays usable even with no client connected (the commands are queued by the
Broadcaster and replayed on connection).

# Perspectives

The three presets are rebuilt in TypeScript (as the perspectives module rebuilds them in
Python); the user layouts are dockview's opaque JSON, one file per perspective under
``RETINA_CONFIG_DIR``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..library import _slug
from ..paths import config_path

if TYPE_CHECKING:
    from .broadcast import Broadcaster

#: Stable panel ids — contract shared with the frontend (web/src/shell/panels.ts).
#: **Public** ids: a recipe names them literally (``app.layout.show('console')``).
PANELS = (
    "explorer",
    "files",
    "windows",
    "history",
    "library",
    "header",
    "stf",
    "doc",
    "home",
    "desktop",
    "pipeline",
    "selector",
    "lightcurve",
    "settings",
    "credits",
    "rtp",
    "console",
    "chat",
)

#: Exclusive sidebar group: only one visible at a time (VS Code rule).
SIDEBAR_PANELS = ("explorer", "files", "windows", "history", "library", "header")

#: The three collapsible **zones** of the shell. Same names as the CSS ``grid-area``s and as
#: the ``data-*`` attributes of ``.workbench``: one vocabulary, from the CSS to the console.
#:
#: A zone has **no** state of its own: it is visible iff one of its panels is. Making it a
#: second mirror would force ``report()`` to reconcile two states for the same thing.
ZONES = ("sidebar", "bottom", "right")
ZONE_PANELS: dict[str, tuple[str, ...]] = {
    "sidebar": SIDEBAR_PANELS,
    "bottom": ("console", "rtp"),
    "right": ("stf", "chat"),
}
#: Panel reopened when expanding a zone we have no memory of.
ZONE_FALLBACK = {"sidebar": "explorer", "bottom": "console", "right": "stf"}

#: Built-in perspectives, rebuilt on the TypeScript side.
BUILTIN_PERSPECTIVES = ("Processing", "Inspection", "Script")

#: Initial visibility — matches the "Processing" preset.
DEFAULT_VISIBLE = {
    "explorer": True,
    "files": False,
    "windows": False,
    "history": False,
    "library": False,
    "header": False,
    "stf": True,
    "doc": False,
    # False: a welcome panel open by default would reopen at every reloaded perspective. It
    # opens on decision — an empty session, or an explicit command.
    "home": False,
    "desktop": False,
    "pipeline": False,
    "settings": False,
    "credits": False,
    "selector": False,
    "lightcurve": False,
    "rtp": False,
    "console": True,
    "chat": False,
}


def _perspectives_root() -> Path:
    """Same config root as the library, neighboring folder."""
    return config_path("perspectives")


class PerspectiveStore:
    """User layouts: one JSON file per perspective."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or _perspectives_root()

    def names(self) -> list[str]:
        if not self._root.is_dir():
            return []
        names = []
        for path in sorted(self._root.glob("*.json")):
            try:
                names.append(json.loads(path.read_text(encoding="utf-8"))["name"])
            except (OSError, ValueError, KeyError):
                continue  # corrupt file: we skip it rather than break the whole list
        return names

    def _path(self, name: str) -> Path:
        return self._root / f"{_slug(name)}.json"

    def save(self, name: str, blob: object) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = {"name": name, "version": 1, "layout": blob}
        self._path(name).write_text(json.dumps(payload), encoding="utf-8")

    def load(self, name: str) -> object | None:
        path = self._path(name)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["layout"]
        except (OSError, ValueError, KeyError):
            return None

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)


class WebLayoutBackend:
    """The 13 methods of the ``LayoutBackend``, served from a local mirror."""

    def __init__(self, broadcast: Broadcaster, store: PerspectiveStore | None = None) -> None:
        self._broadcast = broadcast
        self._store = store or PerspectiveStore()
        self._visible = dict(DEFAULT_VISIBLE)
        self._open_processes: list[str] = []
        self._locked = False
        #: Last **non-empty** panel set of each zone. This is not state, it is an ergonomics
        #: cache: collapsing then expanding the sidebar must reopen History if that is what
        #: it was, not fall back to Explorer. At worst it reopens the wrong panel.
        self._zone_memory: dict[str, tuple[str, ...]] = {}

    # --- commands to the client -----------------------------------------------
    def _command(self, op: str, **args: object) -> None:
        self._broadcast.notify("layout.command", {"op": op, **args})

    # --- panels (reads: local mirror, immediate) ------------------------------
    def panels(self) -> list[str]:
        return list(PANELS)

    def is_visible(self, panel: str) -> bool:
        self._check(panel)
        return self._visible.get(panel, False)

    def set_visible(self, panel: str, visible: bool) -> None:
        self._check(panel)
        self._visible[panel] = bool(visible)
        self._remember()
        self._command("set_visible", panel=panel, visible=bool(visible))

    def activate(self, panel: str) -> None:
        """Reveals ``panel`` alone in its exclusive group (VS Code-style sidebar)."""
        self._check(panel)
        if panel in SIDEBAR_PANELS:
            for other in SIDEBAR_PANELS:
                self._visible[other] = other == panel
        else:
            self._visible[panel] = True
        self._remember()
        self._command("activate", panel=panel)

    def _check(self, panel: str) -> None:
        if panel not in PANELS:
            raise ValueError(f"Unknown panel: {panel!r} — available: {list(PANELS)}")

    # --- zones (derived from the panels) --------------------------------------
    def _check_zone(self, zone: str) -> None:
        if zone not in ZONES:
            raise ValueError(f"Unknown zone: {zone!r} — available: {list(ZONES)}")

    def _remember(self) -> None:
        """Records the set of open panels of every zone that has one."""
        for zone, panels in ZONE_PANELS.items():
            current = tuple(p for p in panels if self._visible.get(p))
            if current:
                self._zone_memory[zone] = current

    def zones(self) -> list[str]:
        return list(ZONES)

    def is_zone_visible(self, zone: str) -> bool:
        self._check_zone(zone)
        return any(self._visible.get(p) for p in ZONE_PANELS[zone])

    def set_zone_visible(self, zone: str, visible: bool) -> None:
        self._check_zone(zone)
        if visible:
            if not self.is_zone_visible(zone):
                for panel in self._zone_memory.get(zone) or (ZONE_FALLBACK[zone],):
                    self._visible[panel] = True
        else:
            self._remember()  # before clearing, otherwise we forget what we are closing
            for panel in ZONE_PANELS[zone]:
                self._visible[panel] = False
        # The command carries the **already resolved** list: the client has no memory logic
        # to duplicate, it just applies.
        self._command(
            "set_zone_visible",
            zone=zone,
            visible=bool(visible),
            panels=[p for p in ZONE_PANELS[zone] if self._visible[p]],
        )

    # --- perspectives ---------------------------------------------------------
    def perspectives(self) -> list[str]:
        return [*BUILTIN_PERSPECTIVES, *self._store.names()]

    def save_perspective(self, name: str) -> None:
        """Asks the client to serialize its layout.

        The write is therefore **asynchronous**: the client answers with
        ``layout.store_perspective``. The ``Protocol`` being synchronous and the only holder
        of the layout being the frontend, there is no alternative — and nothing depends on an
        immediate return.
        """
        self._command("request_save", name=name)

    def open_perspective(self, name: str) -> bool:
        if name in BUILTIN_PERSPECTIVES:
            self._command("load_builtin", name=name)
            return True
        blob = self._store.load(name)
        if blob is None:
            return False
        self._command("load_perspective", name=name, layout=blob)
        return True

    def delete_perspective(self, name: str) -> None:
        self._store.delete(name)

    def reset(self) -> None:
        self._visible = dict(DEFAULT_VISIBLE)
        self._command("reset")

    # --- locking --------------------------------------------------------------
    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self._command("set_locked", locked=self._locked)

    # --- process windows ------------------------------------------------------
    def open_process(self, process_id: str, values: dict | None = None) -> None:
        if process_id not in self._open_processes:
            self._open_processes.append(process_id)
        # Process forms live in the right zone: opening one onto a collapsed zone would show
        # nothing, and `app.layout.open_process('Invert')` would look like a no-op.
        if not self.is_zone_visible("right"):
            self.set_zone_visible("right", True)
        # `values` is not recorded in `_open_processes`: these are *starting* values, which
        # the user then modifies in the form. Keeping them here would replay them at every
        # reconnection and wipe out their settings.
        if values:
            self._command("open_process", process_id=process_id, values=values)
        else:
            self._command("open_process", process_id=process_id)

    def close_process(self, process_id: str) -> None:
        if process_id in self._open_processes:
            self._open_processes.remove(process_id)
        self._command("close_process", process_id=process_id)

    def open_processes(self) -> list[str]:
        return list(self._open_processes)

    # --- current state --------------------------------------------------------
    def state(self) -> dict:
        """Complete mirror, sent in the ``hello``.

        A client that connects must **adopt** this state, not impose its defaults: the server
        outlives connections, and a script may have set the layout before the interface even
        opened. It is the direction of flow that matters here — the reverse would silently
        erase the script's work.
        """
        return {
            "visible": dict(self._visible),
            "zones": {zone: self.is_zone_visible(zone) for zone in ZONES},
            "locked": self._locked,
            "open_processes": list(self._open_processes),
        }

    # --- reconciliation from the client ---------------------------------------
    def report(self, visible: dict[str, bool], open_processes: list[str]) -> None:
        """The client declares its real state — mouse manipulations included.

        Without this, closing a panel by clicking its cross would leave the Python mirror
        convinced it is still open, and ``app.layout.is_visible`` would lie to the console.
        """
        for panel, state in visible.items():
            if panel in PANELS:
                self._visible[panel] = bool(state)
        self._open_processes = [p for p in open_processes if isinstance(p, str)]
        # Universal hook: this is where the zone memory learns about mouse gestures.
        self._remember()

    def store_perspective(self, name: str, layout: object) -> None:
        """Answer to ``request_save``: the client has serialized its layout."""
        self._store.save(name, layout)
