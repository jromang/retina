"""``app.*`` family of the protocol — the scriptable surface, exposed as is.

Discipline: **no handler contains logic**. Each one converts its JSON arguments into domain
objects, then delegates to ``app.*`` — which produces the Python echo. If a handler did
anything else, it would create a capability reachable by the web shell alone: exactly the
architecture bug that console/GUI parity forbids.

Enumerations travel by their **value** (``"pan"``, ``"overlay_red"``) and not by their name:
that is what the snapshot already serializes, and it stays readable in the protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..model.viewport_state import (
    DISPLAY_CHANNELS,
    InteractionMode,
    MaskDisplayMode,
    TransparencyMode,
)
from .rpc import DOMAIN_ERROR, RpcError

if TYPE_CHECKING:
    from ..app import Application
    from ..model.window import ImageWindow

#: ``{RPC name: mutating}``. A mutating call triggers the rebroadcast of the snapshot.
APP_METHODS: dict[str, bool] = {
    # files / windows
    "app.open": True,
    "app.save": True,
    "app.close_window": True,
    "app.reload": True,
    "app.set_active_window": True,
    "app.select_view": True,
    # history
    "app.undo": True,
    "app.redo": True,
    "app.go_to_history": True,
    "app.replay_history": True,
    # recipes / scripts — `run_recipe` is mutating: a recipe opens windows and modifies
    # views. `recipe` and `source` only read.
    "app.run_recipe": True,
    "app.recipe": False,
    "app.source": False,
    # view properties: `set` is mutating (the snapshot changes), `get` only reads.
    # The content does NOT travel through the snapshot — it carries only a summary there,
    # cf. state.py.
    "app.set_view_property": True,
    "app.view_property": False,
    # previews
    "app.new_preview": True,
    "app.modify_preview": True,
    "app.rename_preview": True,
    "app.delete_preview": True,
    "app.store_preview": True,
    # masks
    "app.set_mask": True,
    "app.remove_mask": True,
    "app.set_mask_enabled": True,
    "app.set_mask_inverted": True,
    "app.set_mask_display_mode": True,
    "app.set_mask_visible": True,
    # viewport
    "app.set_zoom": True,
    "app.zoom_in": True,
    "app.zoom_out": True,
    "app.zoom_1_1": True,
    "app.zoom_to_fit": True,
    "app.set_viewport": True,
    "app.set_display_channel": True,
    "app.set_interaction_mode": True,
    "app.set_transparency_mode": True,
    "app.add_overlay": True,
    "app.set_overlays": True,
    "app.clear_overlays": True,
    "app.link_viewports": True,
    "app.unlink_viewports": True,
    "app.set_readout_options": True,
    # STF
    "app.set_stf_enabled": True,
    "app.set_stf": True,
    "app.compute_auto_stf": True,
    "app.apply_stf": True,
    # sequence inspection (Blink)
    "app.blink": True,
    "app.blink_step": True,
    "app.blink_go_to": True,
    # sample raw datasets. Mutating: the download posts notifications, which are part of the
    # snapshot. They do have their own relay, but redeclaring the state one more time costs a
    # few kilobytes — the opposite, believing a fine-grained path is enough, is exactly the
    # bet the project chose not to take (cf. ARCHITECTURE.md).
    "app.download_sample": True,
    # pure reads — no rebroadcast
    "app.readout": False,
    "app.view_ids": False,
    "app.keywords": False,
    "app.blink_state": False,
    "state.snapshot": False,
    "viewport.report_geometry": False,
}


class AppHandlers:
    """JSON ⇄ ``Application`` adapter."""

    def __init__(self, app: Application, snapshots) -> None:
        self._app = app
        self._snapshots = snapshots

    # --- resolution -----------------------------------------------------------
    def _window(self, window: str | None) -> ImageWindow | None:
        """Resolves a window id; ``None`` lets ``app`` pick the active one."""
        if window is None:
            return None
        for win in self._app.windows:
            if win.id == window:
                return win
        raise RpcError(DOMAIN_ERROR, f"unknown window: {window!r}")

    @staticmethod
    def _enum(enum_cls, value: str):
        try:
            return enum_cls(value)
        except ValueError:
            allowed = ", ".join(repr(m.value) for m in enum_cls)
            raise RpcError(
                DOMAIN_ERROR, f"invalid value {value!r} — expected: {allowed}"
            ) from None

    # --- files / windows ------------------------------------------------------
    def open(self, path: str) -> str:
        """Opens an image file and returns the id of the created window."""
        return self._app.open(path).id

    def save(self, path: str, window: str | None = None, stretch: bool = False) -> None:
        """Saves a window's main view. ``stretch`` bakes the STF into the exported copy."""
        self._app.save(path, self._window(window), stretch=stretch)

    def close_window(self, window: str | None = None) -> None:
        """Closes an image window."""
        win = self._window(window)
        self._app.close_window(win)

    def reload(self, window: str | None = None) -> str:
        """Reads a window's original file back, in place.

        Domain errors (a window with no source file, a vanished file, an unknown extension)
        are legitimate refusals the user must read: they surface as ``DOMAIN_ERROR`` rather
        than as an internal error.
        """
        try:
            return self._app.reload(self._window(window)).id
        except (OSError, RuntimeError, ValueError) as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None

    def set_active_window(self, window: str) -> None:
        """Makes a window active."""
        win = self._window(window)
        assert win is not None
        self._app.set_active_window(win)

    def select_view(self, view: str) -> str:
        """Makes a view (main or preview) current."""
        return self._app.select_view(view).id

    # --- sequence inspection ---------------------------------------------------
    def blink(self, frames: list[str]) -> dict | None:
        """Opens a sequence of raw frames and displays the first one."""
        try:
            self._app.blink(frames)
        except (OSError, ValueError) as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return self._app.blink_state()

    def blink_step(self, delta: int = 1) -> dict | None:
        """Advances by one frame — the keyboard or wheel scrolling gesture."""
        return self._blink_move(lambda: self._app.blink_step(int(delta)))

    def blink_go_to(self, index: int) -> dict | None:
        return self._blink_move(lambda: self._app.blink_go_to(int(index)))

    def _blink_move(self, move) -> dict | None:
        try:
            move()
        except RuntimeError as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        # The complete state rather than the index alone: the panel also displays the
        # statistics of the visited frame, and one more round trip to obtain them would
        # show during fast scrolling.
        return self._app.blink_state()

    def blink_state(self) -> dict | None:
        """Current index, count and statistics of the visited frame."""
        return self._app.blink_state()

    def keywords(self, window: str | None = None) -> dict:
        """FITS keywords of a window — what the header panel displays.

        FITS values can be astropy objects (``Undefined``, ``bool_``) that JSON cannot carry:
        we return them as text rather than fail the whole call over one exotic keyword.
        """
        raw_data = self._app.keywords(self._window(window))
        return {str(k): v if isinstance(v, (str, int, float, bool)) or v is None else str(v)
                for k, v in raw_data.items()}

    async def download_sample(self, sample_id: str = "") -> str:
        """Downloads a sample raw dataset and returns its folder.

        ``asyncio.to_thread`` rather than a direct call: a hundred and sixty megabytes on the
        asyncio loop is the whole server frozen — no more WebSocket, no more viewport, no more
        button to cancel. Nor is it a :class:`JobRunner` job: that queue belongs to the server,
        and ``AppHandlers`` deliberately has no access to it. The client therefore holds the
        wait on its promise, and the notification center receives the start then the arrival.
        """
        import asyncio

        try:
            return await asyncio.to_thread(self._app.download_sample, sample_id)
        except (OSError, KeyError, ValueError) as exc:
            # Network down, unknown id, wrong checksum: legitimate refusals the user must
            # read, not server failures.
            raise RpcError(DOMAIN_ERROR, str(exc)) from None

    def view_ids(self) -> list[str]:
        """Every addressable view id, windows and previews alike."""
        ids: list[str] = []
        for win in self._app.windows:
            ids.append(win.main_view.id)
            ids.extend(pv.id for pv in win.previews)
        return ids

    # --- history --------------------------------------------------------------
    def undo(self) -> bool:
        """Undoes the last operation of the current view."""
        return self._app.undo()

    def redo(self) -> bool:
        """Redoes the undone operation."""
        return self._app.redo()

    def go_to_history(self, index: int, window: str | None = None) -> bool:
        """Jumps to an arbitrary state of the history."""
        return self._app.go_to_history(index, self._window(window))

    def replay_history(self, index: int, values: dict | None = None,
                       window: str | None = None) -> bool:
        """Replays a past step with other parameters, and recomputes what follows."""
        return self._app.replay_history(index, values, self._window(window))

    # --- recipes / scripts ----------------------------------------------------
    def recipe(self, view: str | None = None) -> list[dict]:
        """A view's history, as a replayable recipe.

        This is the History Explorer gesture, which builds a ProcessContainer from a view's
        history. The domain already knew how (``View.recipe()``); nothing exposed it, so that
        reproducibility — pillar #4 — stopped at the console.
        """
        target = self._app.view(view) if view else self._app.active_view
        if target is None:
            raise RpcError(DOMAIN_ERROR, "no target view")
        return target.recipe().to_dicts()

    def source(self, process_id: str, values: dict | None = None) -> str:
        """Python source code of a configured instance.

        Equivalent of the "Instance Source Code" button found on *every* process interface
        elsewhere (`JavaScript` and `XPSM` languages). ``to_python_source`` had existed since
        day one and no interface called it.
        """
        from ..process.registry import get

        try:
            instance = get(process_id)(**(values or {}))
        except TypeError as exc:
            raise RpcError(DOMAIN_ERROR, f"{process_id}: invalid parameter — {exc}") from None
        return instance.to_python_source("app.active_view")

    def run_recipe(self, path: str) -> None:
        """Runs a Python recipe file (fresh namespace, ``__file__`` set).

        To be distinguished from ``console.execute``, which sends **text** to the shared
        interpreter: there, the variables stay available at the prompt, which is the point of
        an editor attached to live state. Here we run a **file**, in isolation, as
        ``python -m retina.run`` would. The two gestures coexist because they do not serve the
        same purpose.
        """
        self._app.run_recipe(path)

    # --- previews -------------------------------------------------------------
    def set_view_property(self, view: str, key: str, value=None) -> None:
        """Attaches a piece of data to a view (``null`` removes the key)."""
        self._app.set_view_property(view, key, value)

    def view_property(self, view: str, key: str):
        """Reads a view property. This is where the complete data goes through:
        the snapshot publishes only a summary of it, and the client asks again when ``rev``
        moves."""
        return self._app.view_property(view, key)

    def new_preview(
        self, x0: int, y0: int, x1: int, y1: int,
        preview_id: str = "", window: str | None = None,
    ) -> str:
        """Creates a rectangular preview and returns its id."""
        return self._app.new_preview(x0, y0, x1, y1, preview_id, self._window(window)).id

    def modify_preview(
        self, preview_id: str, x0: int, y0: int, x1: int, y1: int, window: str | None = None
    ) -> str:
        """Moves or resizes a preview."""
        return self._app.modify_preview(
            preview_id, x0, y0, x1, y1, self._window(window)
        ).id

    def rename_preview(self, old_id: str, new_id: str, window: str | None = None) -> str:
        """Renames a preview."""
        return self._app.rename_preview(old_id, new_id, self._window(window)).id

    def delete_preview(self, preview_id: str, window: str | None = None) -> None:
        """Deletes a preview."""
        self._app.delete_preview(preview_id, self._window(window))

    def store_preview(self, preview_id: str, window: str | None = None) -> str:
        """Freezes a volatile preview (its history becomes cumulative)."""
        return self._app.store_preview(preview_id, self._window(window)).id

    # --- masks ----------------------------------------------------------------
    def set_mask(self, source: str, window: str | None = None) -> None:
        """Sets the mask from another view, designated by its id."""
        self._app.set_mask(source, self._window(window))

    def remove_mask(self, window: str | None = None) -> None:
        """Removes the mask."""
        self._app.remove_mask(self._window(window))

    def set_mask_enabled(self, enabled: bool, window: str | None = None) -> None:
        """Enables or disables the mask without losing it."""
        self._app.set_mask_enabled(enabled, self._window(window))

    def set_mask_inverted(self, inverted: bool, window: str | None = None) -> None:
        """Inverts the mask."""
        self._app.set_mask_inverted(inverted, self._window(window))

    def set_mask_display_mode(self, mode: str, window: str | None = None) -> None:
        """Changes how the mask is rendered on the viewport."""
        self._app.set_mask_display_mode(
            self._enum(MaskDisplayMode, mode), self._window(window)
        )

    def set_mask_visible(self, visible: bool, window: str | None = None) -> None:
        """Shows or hides the mask on screen, without touching its effect on processes."""
        self._app.set_mask_visible(visible, self._window(window))

    # --- viewport -------------------------------------------------------------
    def set_zoom(self, zoom: float, window: str | None = None) -> None:
        """Sets the zoom factor."""
        self._app.set_zoom(zoom, self._window(window))

    def zoom_in(self, pivot: list[float] | None = None, window: str | None = None) -> None:
        """Zooms in, optionally around an image point."""
        self._app.zoom_in(tuple(pivot) if pivot else None, self._window(window))

    def zoom_out(self, pivot: list[float] | None = None, window: str | None = None) -> None:
        """Zooms out, optionally around an image point."""
        self._app.zoom_out(tuple(pivot) if pivot else None, self._window(window))

    def zoom_1_1(self, window: str | None = None) -> None:
        """1:1 zoom."""
        self._app.zoom_1_1(self._window(window))

    def zoom_to_fit(self, allow_magnification: bool = False, window: str | None = None) -> None:
        """Adjusts the zoom to show the whole image."""
        self._app.zoom_to_fit(allow_magnification, self._window(window))

    def set_viewport(
        self, center: list[float], zoom: float | None = None, window: str | None = None
    ) -> None:
        """Sets center and zoom at once — the client's pan/zoom gesture boils down to this."""
        self._app.set_viewport(tuple(center), zoom, self._window(window))

    def set_display_channel(self, channel: str, window: str | None = None) -> None:
        """Picks the displayed channel among the 12 available."""
        if channel not in DISPLAY_CHANNELS:
            raise RpcError(
                DOMAIN_ERROR,
                f"unknown channel {channel!r} — expected: {', '.join(DISPLAY_CHANNELS)}",
            )
        self._app.set_display_channel(channel, self._window(window))

    def set_interaction_mode(self, mode: str, window: str | None = None) -> None:
        """Changes what a click on the viewport does."""
        self._app.set_interaction_mode(self._enum(InteractionMode, mode), self._window(window))

    def set_transparency_mode(self, mode: str, window: str | None = None) -> None:
        """Changes how transparent areas are rendered."""
        self._app.set_transparency_mode(
            self._enum(TransparencyMode, mode), self._window(window)
        )

    def add_overlay(
        self, kind: str, window: str | None = None, tag: str = "", **data: Any
    ) -> dict:
        """Paints a vector overlay in image coordinates."""
        try:
            overlay = self._app.add_overlay(kind, self._window(window), tag=tag, **data)
        except ValueError as exc:  # unknown overlay type
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        if overlay is None:
            raise RpcError(DOMAIN_ERROR, "no active window")
        return overlay

    def set_overlays(
        self, tag: str, overlays: list[dict], window: str | None = None
    ) -> list[dict]:
        """Replaces, in a single gesture, the overlays of one tag."""
        try:
            posés = self._app.set_overlays(tag, overlays, self._window(window))
        except ValueError as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        if posés is None:
            raise RpcError(DOMAIN_ERROR, "no active window")
        return posés

    def clear_overlays(self, window: str | None = None, tag: str | None = None) -> None:
        """Removes the overlays; ``tag`` restricts to those of one tool."""
        self._app.clear_overlays(self._window(window), tag)

    def link_viewports(self, windows: list[str] | None = None) -> list[str]:
        """Synchronizes pan and zoom across windows. Without an argument: every open one."""
        try:
            return self._app.link_viewports(windows)
        except KeyError as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None

    def unlink_viewports(self) -> None:
        """Unlinks every viewport."""
        self._app.unlink_viewports()

    def set_readout_options(self, window: str | None = None, **options: Any) -> None:
        """Tunes the readout probe (size, precision, magnifier)."""
        self._app.set_readout_options(self._window(window), **options)

    def readout(
        self, x: float, y: float, n: int | None = None, window: str | None = None
    ) -> dict | None:
        """Probe statistics at image point (x, y).

        Deliberately computed on the server side on the **float32**: the client only has
        float16, insufficient for a probe displayed to 5 decimal places.
        """
        return self._app.readout(x, y, n, self._window(window))

    def report_geometry(
        self, window: str, vw: float, vh: float, dpr: float = 1.0
    ) -> None:
        """The client declares the size of its viewport.

        Without this information, ``zoom_to_fit`` on the server side would have no idea of the
        available area. It is the only client → domain flow that produces no echo: this is
        geometry data, not a user action.
        """
        win = self._window(window)
        if win is not None:
            win.viewport.update_geometry(vw, vh, dpr)

    # --- STF ------------------------------------------------------------------
    def set_stf_enabled(self, enabled: bool, window: str | None = None) -> None:
        """Enables or disables the display stretch."""
        self._app.set_stf_enabled(enabled, self._window(window))

    def compute_auto_stf(self, window: str | None = None) -> dict | None:
        """Computes the auto-stretch (median + MADN) and installs it."""
        stf = self._app.compute_auto_stf(self._window(window))
        if stf is None:
            return None
        return {
            "channels": [
                {"shadows": c.shadows, "midtones": c.midtones, "highlights": c.highlights}
                for c in stf.channels
            ]
        }

    def set_stf(self, channels: list[dict], window: str | None = None) -> None:
        """Installs an explicit STF (interactive editing of the handles)."""
        from ..model.stf import STF, ChannelSTF

        stf = STF(
            channels=[
                ChannelSTF(
                    shadows=float(c.get("shadows", 0.0)),
                    midtones=float(c.get("midtones", 0.5)),
                    highlights=float(c.get("highlights", 1.0)),
                )
                for c in channels
            ]
        )
        self._app.set_stf(stf, self._window(window))

    def apply_stf(self, window: str | None = None) -> str:
        """Bakes the display stretch into the pixels; returns the process id applied."""
        return self._app.apply_stf(self._window(window)).process_id

    # --- state ----------------------------------------------------------------
    def snapshot(self) -> dict:
        """Complete snapshot of the application state (pixels excluded)."""
        return self._snapshots.build()
