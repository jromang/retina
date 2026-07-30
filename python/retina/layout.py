"""Scriptable layout API — console/GUI parity for panels, zones and perspectives.

Pure domain (no shell import). With no backend attached (headless / CLI mode), every method
is a **safe no-op**: a recipe containing ``app.layout.reset()`` runs in batch with no
interface. The web shell attaches
:class:`retina.server.layout_backend.WebLayoutBackend`, which holds the mirror of the layout
and pushes it to the frontend. Every writing method echoes its Python call (Blender style),
like the rest of the ``app`` API.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class LayoutBackend(Protocol):
    """Contract implemented by the shell (no shell dependency here)."""

    def panels(self) -> list[str]: ...
    def is_visible(self, panel: str) -> bool: ...
    def set_visible(self, panel: str, visible: bool) -> None: ...
    def activate(self, panel: str) -> None: ...
    def zones(self) -> list[str]: ...
    def is_zone_visible(self, zone: str) -> bool: ...
    def set_zone_visible(self, zone: str, visible: bool) -> None: ...
    def save_perspective(self, name: str) -> None: ...
    def open_perspective(self, name: str) -> bool: ...
    def delete_perspective(self, name: str) -> None: ...
    def perspectives(self) -> list[str]: ...
    def reset(self) -> None: ...
    def set_locked(self, locked: bool) -> None: ...
    def open_process(self, process_id: str, values: dict | None = None) -> None: ...
    def close_process(self, process_id: str) -> None: ...
    def open_processes(self) -> list[str]: ...


class Layout:
    """Scriptable facade: ``app.layout.show('console')``, ``app.layout.load('Script')``…

    Stable panel ids (see :meth:`panels`); the open processes are addressed through
    :meth:`open_process`/:meth:`open_processes` (multiple tool windows).
    """

    def __init__(self, echo: Callable[[str], None]) -> None:
        self._echo = echo
        self._backend: LayoutBackend | None = None
        self._locked = False

    def _attach(self, backend: LayoutBackend | None) -> None:
        """Called by the shell at construction (and with ``None`` when it closes)."""
        self._backend = backend

    # --- panels ---------------------------------------------------------------
    def panels(self) -> list[str]:
        """Ids of the available fixed panels (``[]`` when headless)."""
        return [] if self._backend is None else self._backend.panels()

    def is_visible(self, panel: str) -> bool:
        return False if self._backend is None else self._backend.is_visible(panel)

    def show(self, panel: str) -> None:
        if self._backend is not None:
            self._backend.set_visible(panel, True)
        self._echo(f"app.layout.show({panel!r})")

    def hide(self, panel: str) -> None:
        if self._backend is not None:
            self._backend.set_visible(panel, False)
        self._echo(f"app.layout.hide({panel!r})")

    def toggle(self, panel: str) -> None:
        if self._backend is not None:
            self._backend.set_visible(panel, not self._backend.is_visible(panel))
        self._echo(f"app.layout.toggle({panel!r})")

    def activate(self, panel: str) -> None:
        """Reveal ``panel`` **alone** within its group (VS Code style sidebar).

        Like :meth:`show`, but hides the other panels of the same exclusive group on the way:
        the left sidebar zone displays only one view at a time. A panel outside a group
        (console…) behaves exactly like ``show``.
        """
        if self._backend is not None:
            self._backend.activate(panel)
        self._echo(f"app.layout.activate({panel!r})")

    # --- collapsible zones ----------------------------------------------------
    def zones(self) -> list[str]:
        """Ids of the collapsible zones: ``sidebar``, ``bottom``, ``right`` (``[]`` headless).

        A zone groups panels; it is visible as soon as one of them is. Collapsing a zone
        closes all its panels, expanding it reopens **those that were open** — the shell
        remembers the last open set.
        """
        return [] if self._backend is None else self._backend.zones()

    def is_zone_visible(self, zone: str) -> bool:
        return False if self._backend is None else self._backend.is_zone_visible(zone)

    def show_zone(self, zone: str) -> None:
        if self._backend is not None:
            self._backend.set_zone_visible(zone, True)
        self._echo(f"app.layout.show_zone({zone!r})")

    def hide_zone(self, zone: str) -> None:
        if self._backend is not None:
            self._backend.set_zone_visible(zone, False)
        self._echo(f"app.layout.hide_zone({zone!r})")

    def toggle_zone(self, zone: str) -> None:
        if self._backend is not None:
            self._backend.set_zone_visible(zone, not self._backend.is_zone_visible(zone))
        self._echo(f"app.layout.toggle_zone({zone!r})")

    # --- perspectives ---------------------------------------------------------
    def perspectives(self) -> list[str]:
        """Available perspectives: built-in presets + user layouts."""
        return [] if self._backend is None else self._backend.perspectives()

    def save(self, name: str) -> None:
        """Save the current layout under ``name`` (a user perspective)."""
        if self._backend is not None:
            self._backend.save_perspective(name)
        self._echo(f"app.layout.save({name!r})")

    def load(self, name: str) -> bool:
        ok = False if self._backend is None else self._backend.open_perspective(name)
        self._echo(f"app.layout.load({name!r})")
        return ok

    def delete(self, name: str) -> None:
        if self._backend is not None:
            self._backend.delete_perspective(name)
        self._echo(f"app.layout.delete({name!r})")

    def reset(self) -> None:
        """Return to the default layout (the antidote to broken layouts)."""
        if self._backend is not None:
            self._backend.reset()
        self._echo("app.layout.reset()")

    # --- locking --------------------------------------------------------------
    @property
    def locked(self) -> bool:
        return self._locked

    def lock(self, locked: bool = True) -> None:
        """(Un)lock the layout: no more accidental detaching/closing."""
        self._locked = bool(locked)
        if self._backend is not None:
            self._backend.set_locked(self._locked)
        self._echo(f"app.layout.lock({self._locked})")

    # --- process windows (multiple) -------------------------------------------
    def open_process(self, process_id: str, values: dict | None = None) -> None:
        """Open (or bring to the front) the process's tool window.

        ``values`` pre-fills the form. That is what makes it possible to open a recipe step
        exactly as it was recorded — and, in the console, to pick a setting back up without
        retyping it: ``app.layout.open_process('GaussianConvolution', {'sigma': 3.5})``.
        """
        if self._backend is not None:
            self._backend.open_process(process_id, values)
        if values:
            self._echo(f"app.layout.open_process({process_id!r}, {values!r})")
        else:
            self._echo(f"app.layout.open_process({process_id!r})")

    def close_process(self, process_id: str) -> None:
        if self._backend is not None:
            self._backend.close_process(process_id)
        self._echo(f"app.layout.close_process({process_id!r})")

    def open_processes(self) -> list[str]:
        """Ids of the processes whose tool window is open."""
        return [] if self._backend is None else self._backend.open_processes()
