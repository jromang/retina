"""``layout.*`` family of the protocol.

Two natures of message coexist here, and the distinction matters:

**User actions** (clicking an activity-bar icon, toggling the console) go through
``app.layout.*`` — hence through the domain, hence **with a Python echo**. Clicking
"Explorer" writes ``app.layout.activate('explorer')`` in the console, exactly as if the user
had typed it. Routing these calls straight to the backend would short-circuit the echo and
create a capability reserved to the interface: the architecture bug that parity forbids.

**Client reports** (``layout.report``, ``layout.store_perspective``) go to the backend
without passing through ``app.layout``: they are not actions, but the frontend's answer to a
command, or the declaration of its real state after a mouse manipulation. Echoing them would
pollute the console with noise the user did not cause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..app import Application
    from .layout_backend import WebLayoutBackend

#: ``{RPC name: mutating}``. No layout method dirties the snapshot *by itself*: the mirror is
#: already up to date on the Python side and the client knows its own state. Only
#: ``open_process``/``close_process`` appear in the snapshot, hence their marking.
LAYOUT_METHODS: dict[str, bool] = {
    "layout.panels": False,
    "layout.is_visible": False,
    "layout.perspectives": False,
    "layout.open_processes": False,
    "layout.show": False,
    "layout.hide": False,
    "layout.toggle": False,
    "layout.activate": False,
    "layout.zones": False,
    "layout.is_zone_visible": False,
    "layout.show_zone": False,
    "layout.hide_zone": False,
    "layout.toggle_zone": False,
    "layout.save": False,
    "layout.load": False,
    "layout.delete": False,
    "layout.reset": False,
    "layout.lock": False,
    "layout.open_process": True,
    "layout.close_process": True,
    # client → server, without echo
    "layout.report": False,
    "layout.store_perspective": False,
}


class LayoutHandlers:
    def __init__(self, app: Application, backend: WebLayoutBackend) -> None:
        self._app = app
        self._backend = backend

    # --- reads ----------------------------------------------------------------
    def panels(self) -> list[str]:
        """Stable ids of the fixed panels."""
        return self._app.layout.panels()

    def is_visible(self, panel: str) -> bool:
        """Is a panel displayed?"""
        return self._app.layout.is_visible(panel)

    def perspectives(self) -> list[str]:
        """Available perspectives: built-in presets + user layouts."""
        return self._app.layout.perspectives()

    def open_processes(self) -> list[str]:
        """Ids of the processes whose tool window is open."""
        return self._app.layout.open_processes()

    def zones(self) -> list[str]:
        """Ids of the collapsible zones: sidebar, bottom, right."""
        return self._app.layout.zones()

    def is_zone_visible(self, zone: str) -> bool:
        """Is a zone expanded? (true as soon as one of its panels is visible)"""
        return self._app.layout.is_zone_visible(zone)

    # --- actions (via app.layout → Python echo) -------------------------------
    def show(self, panel: str) -> None:
        """Displays a panel."""
        self._app.layout.show(panel)

    def hide(self, panel: str) -> None:
        """Hides a panel."""
        self._app.layout.hide(panel)

    def toggle(self, panel: str) -> None:
        """Toggles a panel's visibility."""
        self._app.layout.toggle(panel)

    def activate(self, panel: str) -> None:
        """Reveals a panel alone in its group (exclusive sidebar)."""
        self._app.layout.activate(panel)

    def show_zone(self, zone: str) -> None:
        """Expands a zone, reopening the panels that were in it."""
        self._app.layout.show_zone(zone)

    def hide_zone(self, zone: str) -> None:
        """Collapses a zone (closes all its panels)."""
        self._app.layout.hide_zone(zone)

    def toggle_zone(self, zone: str) -> None:
        """Toggles a zone's collapsed state."""
        self._app.layout.toggle_zone(zone)

    def save(self, name: str) -> None:
        """Saves the current layout under a name."""
        self._app.layout.save(name)

    def load(self, name: str) -> bool:
        """Loads a perspective (preset or user)."""
        return self._app.layout.load(name)

    def delete(self, name: str) -> None:
        """Deletes a user perspective."""
        self._app.layout.delete(name)

    def reset(self) -> None:
        """Returns to the default layout."""
        self._app.layout.reset()

    def lock(self, locked: bool = True) -> None:
        """(Un)locks the layout."""
        self._app.layout.lock(locked)

    def open_process(self, process_id: str, values: dict | None = None) -> None:
        """Opens a process's tool window, optionally pre-filled."""
        self._app.layout.open_process(process_id, values)

    def close_process(self, process_id: str) -> None:
        """Closes a process's tool window."""
        self._app.layout.close_process(process_id)

    # --- client reports (without echo) ----------------------------------------
    def report(self, visible: dict[str, bool], open_processes: list[str]) -> None:
        """The client declares its real layout state."""
        self._backend.report(visible, open_processes)

    def store_perspective(self, name: str, layout: Any) -> None:
        """The client's answer to a perspective-save request."""
        self._backend.store_perspective(name, layout)
