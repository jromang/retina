"""ImageWindow — container for a main view + previews + metadata.

A window owns the main view, its previews (named sub-regions that are themselves ``View``
objects) and the FITS keywords, and delegates undo/redo to the current view.
"""

from __future__ import annotations

import numpy as np

from ..i18n import translate as _t
from .image import Image
from .view import View
from .viewport_state import ViewportState


class Preview(View):
    """A named rectangular sub-region of a window — a fully-fledged View.

    **Volatile semantics** (the default): on every new process, the preview restarts from its
    *base* = the corresponding region of the CURRENT state of the main view. Re-applying
    therefore undoes the previous attempt automatically — the tune → apply → look loop never
    calls for an Undo, for any process. ``store()`` freezes the preview into a standalone
    object with a cumulative history.
    """

    def __init__(self, window, rect: tuple[int, int, int, int], preview_id: str):
        x0, y0, x1, y1 = rect
        sub = Image(window.main_view.image.data[y0:y1, x0:x1, :])
        super().__init__(sub, view_id=preview_id, is_preview=True, window=window)
        self.rect = (x0, y0, x1, y1)
        self.volatile = True

    def reset_from_base(self) -> None:
        """Re-slice the region from the current main view and start over."""
        from .view import HistoryEntry

        w = self.window.main_view.image.width
        h = self.window.main_view.image.height
        x0, y0, x1, y1 = self.rect
        x0, x1 = max(0, min(x0, w - 1)), max(1, min(x1, w))
        y0, y1 = max(0, min(y0, h - 1)), max(1, min(y1, h))
        self.rect = (x0, y0, x1, y1)
        base = Image(self.window.main_view.image.data[y0:y1, x0:x1, :])
        self._image = base
        self._history = [HistoryEntry("initial", base)]
        self._index = 0

    def begin_process(self, label: str = "", process: object | None = None) -> None:
        if self.volatile:
            self.reset_from_base()
        super().begin_process(label, process)

    def store(self) -> None:
        """Freeze the preview: cumulative history, independent of the main view."""
        self.volatile = False

    def set_rect(self, rect: tuple[int, int, int, int]) -> None:
        """Move or resize the preview (EDIT_PREVIEW mode) and resynchronize."""
        self.rect = tuple(int(v) for v in rect)
        self.reset_from_base()


class ImageWindow:
    _counter = 0

    def __init__(self, image: Image, window_id: str = "", file_path: str | None = None):
        ImageWindow._counter += 1
        self.id = window_id or f"Image{ImageWindow._counter:02d}"
        self.file_path = file_path
        self.keywords: dict[str, object] = {}  # FITS keywords
        self.wcs = None  # astrometric solution (astropy.wcs.WCS) after plate-solving
        self.mask: Image | None = None  # mask limiting the effect of processes
        # Id of the view the mask came from. The mask itself is an `Image`, which does not say
        # where it came from; yet the history must be able to **replay** a step with the mask
        # it actually used, and designating it by id is already the convention of
        # `ProcessContainer.set_mask`.
        self.mask_source_id: str | None = None
        self.mask_enabled = True
        self.mask_inverted = False
        self._main_view = View(image, view_id=self.id, is_preview=False, window=self)
        self._current_view = self._main_view
        self._previews: dict[str, Preview] = {}
        self.is_modified = False
        # scriptable display state (zoom/pan/channel/modes) — the pivot of parity
        self.viewport = ViewportState((image.width, image.height))

    @property
    def has_astrometric_solution(self) -> bool:
        return self.wcs is not None

    def image_to_celestial(self, x: float, y: float):
        """Pixel → celestial coordinates (SkyCoord). Requires a WCS (plate-solve)."""
        if self.wcs is None:
            raise RuntimeError(_t("No astrometric solution (run PlateSolve)."))
        return self.wcs.pixel_to_world(x, y)

    def celestial_to_image(self, skycoord):
        """Celestial coordinates (SkyCoord) → pixel (x, y)."""
        if self.wcs is None:
            raise RuntimeError(_t("No astrometric solution (run PlateSolve)."))
        return self.wcs.world_to_pixel(skycoord)

    # --- display: zoom / pan (delegated to ViewportState) ---------------------
    @property
    def zoom(self) -> float:
        return self.viewport.zoom

    @zoom.setter
    def zoom(self, value: float) -> None:
        self.viewport.set_zoom(float(value))

    @property
    def center(self) -> tuple[float, float]:
        return self.viewport.center

    @center.setter
    def center(self, value: tuple[float, float]) -> None:
        self.viewport.set_center(value)

    def image_to_viewport(self, pt: tuple[float, float]) -> tuple[float, float]:
        return self.viewport.image_to_viewport(pt)

    def viewport_to_image(self, pt: tuple[float, float]) -> tuple[float, float]:
        return self.viewport.viewport_to_image(pt)

    def viewport_to_celestial(self, pt: tuple[float, float]):
        """Viewport point → celestial coordinates (composes viewport→image→celestial)."""
        ix, iy = self.viewport_to_image(pt)
        return self.image_to_celestial(ix, iy)

    def select_channel(self, channel: str) -> None:
        self.viewport.set_display_channel(channel)

    def readout(self, x: float, y: float, n: int | None = None) -> dict | None:
        """Statistics of an NxN probe centered on (x, y) in image coordinates.

        Returns one dict per channel (mean/median/min/max) plus the coordinates, or ``None``
        if the point falls outside the image. Reuses the numpy slices of :class:`Image`.
        """
        img = self._current_view.image
        n = self.viewport.readout.probe_size if n is None else int(n)
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < img.width and 0 <= yi < img.height):
            return None
        r = max(0, (n - 1) // 2)
        x0, x1 = max(0, xi - r), min(img.width, xi + r + 1)
        y0, y1 = max(0, yi - r), min(img.height, yi + r + 1)
        patch = img.data[y0:y1, x0:x1, :]
        return {
            "x": xi,
            "y": yi,
            "celestial": self._celestial_at(xi, yi),
            "channels": [
                {
                    "mean": float(np.mean(patch[:, :, c])),
                    "median": float(np.median(patch[:, :, c])),
                    "min": float(np.min(patch[:, :, c])),
                    "max": float(np.max(patch[:, :, c])),
                }
                for c in range(patch.shape[2])
            ],
        }

    def _celestial_at(self, xi: int, yi: int) -> dict | None:
        """RA/Dec (degrees) of the probed pixel, or ``None`` without astrometry.

        Two pitfalls. The WCS belongs to the **window**, whereas the probe works in the frame
        of the current view: on a preview, the rectangle's origin has to be re-applied, or the
        displayed coordinates designate another place in the sky — all the more misleading in
        that they stay plausible. And a degenerate WCS can raise: an unfindable coordinate is
        not a reason to break the readout of pixel values.
        """
        if self.wcs is None:
            return None
        view = self._current_view
        rect = getattr(view, "rect", None)
        x, y = (xi + rect[0], yi + rect[1]) if rect else (xi, yi)
        try:
            coord = self.image_to_celestial(float(x), float(y))
            return {"ra": float(coord.ra.deg), "dec": float(coord.dec.deg)}
        except Exception:
            return None

    # --- views ----------------------------------------------------------------
    @property
    def main_view(self) -> View:
        return self._main_view

    @property
    def current_view(self) -> View:
        return self._current_view

    def set_current_view(self, view: View) -> None:
        self._current_view = view
        self.viewport.set_image_size((view.image.width, view.image.height))

    def replace_image(self, image: Image, keywords: dict | None = None,
                      stf=None, label: str = "reload") -> None:
        """Replace the window's content — **as if it were closed and reopened**.

        This is the mechanism behind ``app.reload``: the file changed on disk, and the window
        must show what it contains now. What follows from that, and is intended:

        - **the history restarts from scratch.** The previous states describe the pixels of a
          file that no longer exists; keeping the undo stack would return to a state derived
          from another image, with nothing to signal it. An undo stack whose entries do not
          follow one another is worse than no stack at all.
        - **the astrometric solution is dropped.** It described the old content; keeping it
          would yield celestial coordinates that are plausible and wrong, the hardest kind of
          bug to see. It is up to the caller to set the new content's solution if it knows it
          — ``app.reload`` reads it back from the file's keywords; otherwise, ``PlateSolve``.
        - **previews are re-sliced** from the new image (rectangles preserved, clamped to the
          new geometry), including those that had been frozen by ``store()``: their cumulative
          history also referred to the old content.
        - **the mask and the STF survive**: these are not file content but settings the user
          placed on the window. An STF supplied by the file (XISF embeds one) replaces the
          current one; ``None`` leaves it in place, which keeps the screen stable when
          reloading a FITS.
        """
        from .view import HistoryEntry

        self._main_view.restore_history([HistoryEntry(label, image)], 0)
        if keywords is not None:
            self.keywords = dict(keywords)
        if stf is not None:
            self._main_view.stf = stf
        self.wcs = None
        for preview in self._previews.values():
            preview.reset_from_base()
        # The displayed geometry follows the current view — the reloaded image may not have
        # the same size as the old one (a crop performed outside, for instance).
        self.viewport.set_image_size(
            (self._current_view.image.width, self._current_view.image.height)
        )
        # The content has just been re-read: there is nothing unsaved left.
        self.is_modified = False

    # --- previews -------------------------------------------------------------
    def create_preview(self, x0: int, y0: int, x1: int, y1: int, preview_id: str = "") -> Preview:
        """Create a preview. The default identifier is **prefixed with the window name**.

        This prefix is not cosmetic. View identifiers are the **global** addressing of pixels:
        the URL is ``/api/pixels/<id>.f16``, the generation is held under ``view:<id>``, and
        ``app.view(id)`` sweeps every window. Per-window numbering produced two ``Preview01``
        as soon as two images were open with a preview created in each — the most ordinary
        case of all. The generation key then received alternately one's pixels and the other's,
        incremented on every snapshot, and the client could never again request a valid
        generation: the preview did not display, on a cascade of 409s. Same precedent as
        ``light_StarMask`` for windows created by a process.
        """
        pid = preview_id or f"{self.id}_Preview{len(self._previews) + 1:02d}"
        pv = Preview(self, (x0, y0, x1, y1), pid)
        self._previews[pid] = pv
        return pv

    def preview_by_id(self, preview_id: str) -> Preview | None:
        return self._previews.get(preview_id)

    @property
    def previews(self) -> list[Preview]:
        return list(self._previews.values())

    def delete_preview(self, preview_id: str) -> None:
        pv = self._previews.pop(preview_id, None)
        if pv is not None and self._current_view is pv:
            self.set_current_view(self._main_view)

    def rename_preview(self, old_id: str, new_id: str) -> Preview:
        new_id = new_id.strip()
        if not new_id:
            raise ValueError(_t("Empty preview identifier."))
        if new_id in self._previews or new_id == self.id:
            raise ValueError(_t("Identifier already taken: {new_id!r}").format(new_id=new_id))
        pv = self._previews.pop(old_id)
        pv.id = new_id
        self._previews[new_id] = pv
        return pv

    # --- mask -----------------------------------------------------------------
    def set_mask(self, image: Image, inverted: bool = False,
                 source_id: str | None = None) -> None:
        self.mask = image
        self.mask_source_id = source_id
        self.mask_inverted = inverted
        self.mask_enabled = True

    def remove_mask(self) -> None:
        self.mask = None
        self.mask_source_id = None

    def mask_array(
        self,
        shape: tuple[int, int, int],
        rect: tuple[int, int, int, int] | None = None,
    ) -> np.ndarray | None:
        """Effective mask ``(H, W, 1)`` in [0,1] (inversion applied), or None.

        White (1) = process fully applied; black (0) = protected.

        ``rect`` ``(x0, y0, x1, y1)`` crops the mask before comparison: the mask belongs to
        the **window**, but a process may target a preview, whose image is the corresponding
        sub-region. A window mask therefore applies to its previews without anyone having to
        resize it.
        """
        if self.mask is None or not self.mask_enabled:
            return None
        m = self.mask.data
        if rect is not None:
            x0, y0, x1, y1 = rect
            m = m[y0:y1, x0:x1, :]
        if m.shape[0] != shape[0] or m.shape[1] != shape[1]:
            raise ValueError(
                _t("Mask {mask_shape} != image {image_shape}: incompatible dimensions.").format(
                    mask_shape=m.shape[:2], image_shape=shape[:2]
                )
            )
        if m.shape[2] > 1:
            m = m.mean(axis=2, keepdims=True)
        m = np.clip(m, 0.0, 1.0)
        return (1.0 - m) if self.mask_inverted else m

    # --- history (delegated to the current view) ------------------------------
    def undo(self) -> bool:
        return self._current_view.undo()

    def redo(self) -> bool:
        return self._current_view.redo()

    def __repr__(self) -> str:
        return (
            f"ImageWindow(id={self.id!r}, {self._main_view.image!r}, "
            f"previews={len(self._previews)})"
        )
