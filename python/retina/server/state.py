"""``SnapshotBuilder`` — serialization of the application state for the frontend.

# Why a complete snapshot rather than fine-grained events

The domain emits **nothing**: no "process applied", no "view modified", no "history changed".
Only ``on_echo``, ``on_windows_changed`` and ``ViewportState.on_change`` exist. Guessing what
changed after each call would require instrumenting the ~115 processes and every method of
``app`` — a lot of fragile code to save a few kilobytes.

The complete snapshot is a few KB even with ten windows open, goes out at most once per loop
turn (cf. :class:`~retina.server.broadcast.Broadcaster`), and lets the frontend be a simple
``render(snapshot)`` function. The only bulky data — the pixels — is excluded from it: it
travels over HTTP, addressed by ``pixel_gen``.

# ``pixel_gen``: detecting a pixel change without instrumenting the core

Every view exposes a counter incremented as soon as its numpy array is no longer *the same
object*. ``end_process``, ``undo``, ``redo`` and ``go_to`` all replace ``View._image`` — the
counter therefore moves mechanically, without a line added to the domain. Tracking is done by
**weak** reference: keeping a strong one would keep every image of a history alive.

Accepted limitation: an **in-place** mutation (``Image.set_sample``) does not change the
array's identity and would go unnoticed. Hence :meth:`invalidate`, to be called explicitly in
that case.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..app import Application
    from ..model.view import View
    from ..model.window import ImageWindow


class SnapshotBuilder:
    """Builds the JSON snapshot and keeps the pixel generation counters."""

    def __init__(self, app: Application) -> None:
        self._app = app
        self._rev = 0
        self._gen: dict[str, int] = {}
        self._refs: dict[str, weakref.ReferenceType] = {}
        #: Filled in by the server — in-flight jobs are part of the visible state.
        self.jobs_provider: Callable[[], list[dict]] | None = None

    # --- pixel generations ----------------------------------------------------
    def _gen_for(self, key: str, data: Any) -> int:
        """Current generation of ``key``, incremented if the array has been replaced."""
        ref = self._refs.get(key)
        current = ref() if ref is not None else None
        if current is not data:
            self._gen[key] = self._gen.get(key, 0) + 1
            try:
                self._refs[key] = weakref.ref(data)
            except TypeError:  # pragma: no cover — an ndarray is always weak-referenceable
                self._refs.pop(key, None)
        return self._gen[key]

    def pixel_gen(self, view_id: str) -> int | None:
        """Generation published for this view, or ``None`` if never seen."""
        return self._gen.get(f"view:{view_id}")

    def mask_gen(self, window_id: str) -> int | None:
        return self._gen.get(f"mask:{window_id}")

    def invalidate(self, key: str) -> None:
        """Forces a generation bump — for in-place mutations, invisible otherwise."""
        self._refs.pop(key, None)

    # --- construction ---------------------------------------------------------
    def build(self) -> dict:
        self._rev += 1
        app = self._app
        active = app.active_window
        active_view = app.active_view
        return {
            "rev": self._rev,
            "active_window": active.id if active is not None else None,
            "active_view": active_view.id if active_view is not None else None,
            "windows": [self._window(win) for win in app.windows],
            # Derived from the domain, never from a client-side mirror: the link is also set
            # from the console, and two connected clients must see the same state.
            "linked_viewports": app.linked_viewports(),
            # Current project: the title bar names it, and the welcome screen steps aside as
            # soon as a session is loaded. Like the rest, derived from the domain — an
            # `app.open_project` typed in the console must change the title.
            "project": app.project_path,
            "layout": {
                "open_processes": app.layout.open_processes(),
                "locked": app.layout.locked,
                "panels": app.layout.panels(),
            },
            "jobs": [] if self.jobs_provider is None else self.jobs_provider(),
            # The whole center (bounded by NotificationCenter.MAX): this is what repairs the
            # bell after a reconnection, as `jobs` repairs the progress bar.
            "notifications": [n.to_dict() for n in app.notifications],
        }

    def _window(self, win: ImageWindow) -> dict:
        image = win.main_view.image
        return {
            "id": win.id,
            "file_path": win.file_path,
            "is_modified": bool(win.is_modified),
            "width": image.width,
            "height": image.height,
            "channels": image.channels,
            "keyword_count": len(win.keywords),
            "has_wcs": bool(win.has_astrometric_solution),
            "current_view": win.current_view.id,
            "mask": self._mask(win),
            "views": [self._view(win.main_view)] + [self._view(pv) for pv in win.previews],
            "viewport": self._viewport(win),
        }

    def _mask(self, win: ImageWindow) -> dict | None:
        if win.mask is None:
            return None
        return {
            "enabled": bool(win.mask_enabled),
            "inverted": bool(win.mask_inverted),
            "width": win.mask.width,
            "height": win.mask.height,
            "channels": win.mask.channels,
            "gen": self._gen_for(f"mask:{win.id}", win.mask.data),
        }

    def _view(self, view: View) -> dict:
        image = view.image
        entry: dict = {
            "id": view.id,
            "is_preview": view.is_preview,
            "width": image.width,
            "height": image.height,
            "channels": image.channels,
            "pixel_gen": self._gen_for(f"view:{view.id}", image.data),
            "history": {
                "labels": view.history_labels(),
                "index": view.history_index,
                "can_undo": view.can_go_backward,
                "can_redo": view.can_go_forward,
                # One line per entry: the `process_id` that produced it, or `null` for the
                # initial state and for what is not replayable. It is a small thing (a short
                # string per step) and it is enough for the panel to offer editing only
                # where it will work — offering a pencil that fails would be worse than
                # offering nothing.
                "processes": [
                    None if e.process is None else getattr(e.process, "process_id", None)
                    for e in view.history_entries()
                ],
            },
            "stf": self._stf(view),
        }
        # Properties: a **summary**, never the data. DynamicPSF's measurements run to
        # hundreds of stars; republishing them at every `state.changed`, for every view,
        # would cost tens of KB per burst — whereas what the client needs to know fits in
        # two numbers: what exists, and whether it has changed since (`rev`). The content is
        # requested through `view.get_property`.
        if view.properties:
            entry["properties"] = {
                "rev": view.properties_rev,
                "keys": sorted(view.properties),
            }
        if view.is_preview:
            entry["rect"] = list(view.rect)
            entry["volatile"] = bool(view.volatile)
        return entry

    @staticmethod
    def _stf(view: View) -> dict:
        """``{enabled, channels}``. The channel list comes from the domain (``STF.to_dict``):
        the project format and the snapshot must speak the same language, otherwise the client
        would learn two forms of the same data."""
        stf = view.stf
        return {
            "enabled": bool(view.stf_enabled),
            "channels": [] if stf is None else stf.to_dict()["channels"],
        }

    @staticmethod
    def _viewport(win: ImageWindow) -> dict:
        return win.viewport.to_dict()
