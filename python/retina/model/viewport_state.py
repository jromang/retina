"""ViewportState — the scriptable display state of an :class:`ImageWindow`, shell-free.

The pivot of **console/GUI parity** (see ARCHITECTURE.md): everything about a window's
display — zoom, pan (center), displayed channel, interaction mode, mask display mode, readout
options — lives here, in the shell-free domain. The WebGL renderer is only a *reflection* of
this state (it renders it) and an *input source* (it writes back the device geometry: viewport
size + device pixel ratio).

The viewport ⇄ image coordinate transforms are **pure math**, computed from
``zoom``/``center``/``vw``/``vh`` (image convention, y downward, like the widget): they
therefore work **without a widget** (headless), the geometry having sensible defaults.

Camera ↔ state synchronization: a scripted mutation (``window.zoom = 2``) fires ``on_change``,
which the widget hooks in order to re-derive its camera; conversely the widget calls
``update_geometry`` after a pan/zoom/resize to keep the state authoritative. Same pattern as
``app.on_echo``: a slot the domain exposes and the shell fills in.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from ..i18n import translate as _t


class InteractionMode(Enum):
    """What a click or drag does on the viewport."""

    READOUT = "readout"          # hover → readout (pixel value / coordinates)
    ZOOM_IN = "zoom_in"          # click → centered zoom in
    ZOOM_OUT = "zoom_out"        # click → centered zoom out
    PAN = "pan"                  # drag → moves the view
    CENTER = "center"            # click → recenters on the cursor
    NEW_PREVIEW = "new_preview"  # drag → defines a new preview
    EDIT_PREVIEW = "edit_preview"  # drag → modifies an existing preview
    DYNAMIC = "dynamic"          # dynamic tool (e.g. DBE sampling)


class TransparencyMode(Enum):
    """Rendering of transparent areas (alpha < 1)."""

    HIDE = "hide"                     # show nothing (viewport background)
    BACKGROUND_BRUSH = "brush"        # checkerboard (default)
    COLOR = "color"                   # solid color


class MaskDisplayMode(Enum):
    """How the mask is overlaid on the image."""

    REPLACE = "replace"          # show the mask alone (blink comparison)
    MULTIPLY = "multiply"        # mask multiplied into the image (traditional)
    OVERLAY_RED = "overlay_red"  # colored overlay (default)
    OVERLAY_GREEN = "overlay_green"
    OVERLAY_BLUE = "overlay_blue"
    OVERLAY_YELLOW = "overlay_yellow"
    OVERLAY_MAGENTA = "overlay_magenta"
    OVERLAY_CYAN = "overlay_cyan"
    OVERLAY_ORANGE = "overlay_orange"
    OVERLAY_VIOLET = "overlay_violet"


# RGBA (0..1) of the overlay modes — used by the renderer.
OVERLAY_COLORS: dict[MaskDisplayMode, tuple[float, float, float]] = {
    MaskDisplayMode.OVERLAY_RED: (1.0, 0.0, 0.0),
    MaskDisplayMode.OVERLAY_GREEN: (0.0, 1.0, 0.0),
    MaskDisplayMode.OVERLAY_BLUE: (0.0, 0.0, 1.0),
    MaskDisplayMode.OVERLAY_YELLOW: (1.0, 1.0, 0.0),
    MaskDisplayMode.OVERLAY_MAGENTA: (1.0, 0.0, 1.0),
    MaskDisplayMode.OVERLAY_CYAN: (0.0, 1.0, 1.0),
    MaskDisplayMode.OVERLAY_ORANGE: (1.0, 0.5, 0.0),
    MaskDisplayMode.OVERLAY_VIOLET: (0.6, 0.0, 1.0),
}


# Supported display channels (RGB, individual channels, luminance, CIE L*a*b*, HSV/HSI).
DISPLAY_CHANNELS = (
    "rgb", "red", "green", "blue", "L",
    "cie_L", "cie_a", "cie_b",
    "hue", "saturation", "value", "intensity",
)


@dataclass
class ReadoutOptions:
    """Readout options (the hover statistics probe)."""

    probe_size: int = 1          # side of the NxN probe (odd)
    color_space: str = "rgbk"    # space of the displayed values (cielab/hsv…)
    real: bool = True            # real format [0,1] vs integer
    precision: int = 5           # decimals when real
    # True by default: the viewport displayed its loupe unconditionally as long as nobody read
    # this option. Now that it is honored, leaving it False would *remove* a feature — a
    # newly wired setting must not change what used to be seen.
    show_loupe: bool = True      # magnified loupe on hover

    def to_dict(self) -> dict:
        return {
            "probe_size": int(self.probe_size),
            "color_space": str(self.color_space),
            "real": bool(self.real),
            "precision": int(self.precision),
            "show_loupe": bool(self.show_loupe),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ReadoutOptions:
        base = cls()
        return cls(
            probe_size=int(data.get("probe_size", base.probe_size)),
            color_space=str(data.get("color_space", base.color_space)),
            real=bool(data.get("real", base.real)),
            precision=int(data.get("precision", base.precision)),
            show_loupe=bool(data.get("show_loupe", base.show_loupe)),
        )


#: Defaults for new windows. They are **pushed** here by the application (preferences), never
#: pulled: `model/` must know nothing of the application layer, and this is the same inversion
#: as `i18n.set_preference_source`. Only **new** windows inherit them — changing a default does
#: not rewrite the state of those already open.
_DEFAULTS: dict = {
    "mask_display_mode": MaskDisplayMode.OVERLAY_RED,
    "transparency_mode": TransparencyMode.BACKGROUND_BRUSH,
    "readout": ReadoutOptions(),
}


def configure_defaults(*, mask_display_mode: str | None = None,
                       transparency_mode: str | None = None,
                       readout_probe_size: int | None = None) -> None:
    """Set the defaults for future windows. An unknown value is ignored, not fatal."""
    import contextlib

    if mask_display_mode:
        with contextlib.suppress(ValueError):
            _DEFAULTS["mask_display_mode"] = MaskDisplayMode(mask_display_mode)
    if transparency_mode:
        with contextlib.suppress(ValueError):
            _DEFAULTS["transparency_mode"] = TransparencyMode(transparency_mode)
    if readout_probe_size:
        base = _DEFAULTS["readout"].to_dict()
        base["probe_size"] = int(readout_probe_size)
        _DEFAULTS["readout"] = ReadoutOptions.from_dict(base)


# Zoom bounds (linear factor: 1.0 = 1:1).
_MIN_ZOOM = 1.0 / 64.0
_MAX_ZOOM = 64.0


class ViewportState:
    """Display state of a window. One instance per :class:`ImageWindow`.

    ``image_size`` = (width, height) of the displayed view: serves as the default geometry in
    headless mode and for ``zoom_to_fit``.
    """

    def __init__(self, image_size: tuple[int, int]):
        w, h = image_size
        defects = _DEFAULTS
        self.image_size = (int(w), int(h))
        self.zoom: float = 1.0
        self.center: tuple[float, float] = (w / 2.0, h / 2.0)
        self.display_channel: str = "rgb"
        self.stf_enabled: bool = True
        self.interaction_mode: InteractionMode = InteractionMode.READOUT
        self.mask_display_mode: MaskDisplayMode = defects["mask_display_mode"]
        # Seeing the mask and being *subject* to it are two things (Show Mask vs Enable
        # Mask). `ImageWindow.mask_enabled` decides whether processes honor it; this one
        # decides display only — one often masks blind after having checked.
        self.mask_visible: bool = True
        # A copy, never the reference: a shared default would be mutated by the first window
        # that changes its probe size, and every subsequent one would inherit it.
        self.readout = ReadoutOptions.from_dict(defects["readout"].to_dict())
        # device geometry (reported by the widget; defaults to the image size in headless)
        self.vw: float = float(w)
        self.vh: float = float(h)
        self.dpr: float = 1.0
        # transparency: how to render alpha < 1 areas (checkerboard / color / hidden)
        self.transparency_mode: TransparencyMode = defects["transparency_mode"]
        # dynamic overlays (vector graphics painted by modules/scripts).
        # Pure data: the viewport renders them; in headless they are merely stored.
        self.overlays: list[dict] = []
        # observer slot: the widget hooks it to resynchronize its camera
        self.on_change: Callable[[], None] | None = None

    # --- notification --------------------------------------------------------
    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def set_image_size(self, size: tuple[int, int]) -> None:
        """Adjust the state after an image size change (new view, resample)."""
        self.image_size = (int(size[0]), int(size[1]))

    # --- geometry (reported by the widget, without notification) --------------
    def update_geometry(self, vw: float, vh: float, dpr: float = 1.0) -> None:
        """The widget declares the viewport size (device-independent px) and HiDPI ratio."""
        self.vw = float(vw)
        self.vh = float(vh)
        self.dpr = float(dpr)

    def set_geometry(self, vw: float, vh: float, dpr: float = 1.0) -> None:
        """Explicit alias for setting the geometry in headless mode (tests, scripts)."""
        self.update_geometry(vw, vh, dpr)

    # --- zoom / pan ----------------------------------------------------------
    def set_zoom(self, zoom: float, pivot: tuple[float, float] | None = None) -> None:
        """Set the zoom factor. ``pivot`` (image coords) stays under the cursor if given."""
        zoom = float(min(max(zoom, _MIN_ZOOM), _MAX_ZOOM))
        if pivot is not None:
            # keep the pivot point fixed on screen: adjust the center accordingly
            px, py = pivot
            cx, cy = self.center
            ratio = self.zoom / zoom
            self.center = (px + (cx - px) * ratio, py + (cy - py) * ratio)
        self.zoom = zoom
        self._changed()

    def zoom_in(self, pivot: tuple[float, float] | None = None) -> None:
        self.set_zoom(self.zoom * 2.0, pivot)

    def zoom_out(self, pivot: tuple[float, float] | None = None) -> None:
        self.set_zoom(self.zoom / 2.0, pivot)

    def zoom_1_1(self) -> None:
        self.set_zoom(1.0)

    def set_center(self, center: tuple[float, float]) -> None:
        self.center = (float(center[0]), float(center[1]))
        self._changed()

    def set_viewport(self, center: tuple[float, float], zoom: float | None = None) -> None:
        """Set center (and zoom) in one go."""
        self.center = (float(center[0]), float(center[1]))
        if zoom is not None:
            self.zoom = float(min(max(zoom, _MIN_ZOOM), _MAX_ZOOM))
        self._changed()

    def zoom_to_fit(self, allow_magnification: bool = False) -> None:
        """Pick the largest zoom that shows the whole image, and recenter."""
        w, h = self.image_size
        if w <= 0 or h <= 0 or self.vw <= 0 or self.vh <= 0:
            return
        fit = min(self.vw / w, self.vh / h)
        if not allow_magnification:
            fit = min(fit, 1.0)
        self.zoom = float(min(max(fit, _MIN_ZOOM), _MAX_ZOOM))
        self.center = (w / 2.0, h / 2.0)
        self._changed()

    # --- coordinate transforms (pure math, headless-friendly) -----------------
    def image_to_viewport(self, pt: tuple[float, float]) -> tuple[float, float]:
        """Image point (x, y) → viewport point (device-independent px), y downward."""
        ix, iy = pt
        cx, cy = self.center
        vx = (ix - cx) * self.zoom + self.vw / 2.0
        vy = (iy - cy) * self.zoom + self.vh / 2.0
        return (vx, vy)

    def viewport_to_image(self, pt: tuple[float, float]) -> tuple[float, float]:
        """Viewport point (device-independent px) → image point (x, y), algebraic inverse."""
        vx, vy = pt
        cx, cy = self.center
        ix = (vx - self.vw / 2.0) / self.zoom + cx
        iy = (vy - self.vh / 2.0) / self.zoom + cy
        return (ix, iy)

    def image_scalar_to_viewport(self, s: float) -> float:
        return s * self.zoom

    def viewport_scalar_to_image(self, s: float) -> float:
        return s / self.zoom

    # --- channel / modes ------------------------------------------------------
    def set_display_channel(self, channel: str) -> None:
        if channel not in DISPLAY_CHANNELS:
            raise ValueError(
                _t("Unknown display channel: {channel!r} (expected {choices})").format(
                    channel=channel, choices=DISPLAY_CHANNELS
                )
            )
        self.display_channel = channel
        self._changed()

    def set_stf_enabled(self, enabled: bool) -> None:
        self.stf_enabled = bool(enabled)
        self._changed()

    def set_interaction_mode(self, mode: InteractionMode) -> None:
        self.interaction_mode = mode
        self._changed()

    def set_mask_display_mode(self, mode: MaskDisplayMode) -> None:
        self.mask_display_mode = mode
        self._changed()

    def set_mask_visible(self, visible: bool) -> None:
        self.mask_visible = bool(visible)
        self._changed()

    def set_transparency_mode(self, mode: TransparencyMode) -> None:
        self.transparency_mode = mode
        self._changed()

    # --- dynamic overlays (vector graphics) -----------------------------------
    def add_overlay(self, kind: str, tag: str = "", **data) -> dict:
        """Add a vector overlay in **image** coordinates.

        Five kinds, whose data shape is the contract the renderer expects
        (``web/src/viewport/overlay.ts``):

        - ``markers`` — ``points=[(x, y), ...]``, ``color``, ``size``
        - ``lines``   — ``points=[(x, y), ...]`` (a polyline) or ``segments=[[(x,y), ...], ...]``
          (several polylines), ``color``, ``width``
        - ``text``    — ``items=[{'x': .., 'y': .., 'text': ..}, ...]``, ``color``, ``size``
        - ``ellipses`` — ``items=[{'x','y','rx','ry','theta'}, ...]`` (theta in radians),
          ``color``, ``width``
        - ``rects``   — ``rects=[(x0, y0, x1, y1), ...]``, ``angle`` (degrees), ``color``,
          ``width``

        ``tag`` groups the overlays of one tool, so that :meth:`clear_overlays` can erase only
        its own: two tools open at the same time would erase each other without it.

        E.g. ``add_overlay('markers', points=[(x, y), ...], color=(1,1,0,1), size=10)``.
        Returns the overlay dict (mutable / reusable as a handle).
        """
        if kind not in ("markers", "lines", "text", "ellipses", "rects"):
            raise ValueError(_t("Unknown overlay kind: {kind!r}").format(kind=kind))
        overlay = {"kind": kind, **data}
        if tag:
            overlay["tag"] = tag
        self.overlays.append(overlay)
        self._changed()
        return overlay

    def set_overlays(self, tag: str, overlays: list[dict]) -> list[dict]:
        """Replace **in one gesture** every overlay carrying ``tag``.

        This is the operation an interactive tool needs: it redraws its complete set on every
        change. The "clear then add" sequence looks equivalent but is not, over the network —
        two RPC calls are not ordered, and a stale set arriving late stayed on screen. Here
        there is a single mutation, hence nothing to reorder.
        """
        if not tag:
            raise ValueError(_t("set_overlays requires a tag (otherwise use clear_overlays)."))
        posés = []
        for overlay in overlays:
            kind = overlay.get("kind", "")
            data = {k: v for k, v in overlay.items() if k not in ("kind", "tag")}
            posés.append({"kind": kind, **data, "tag": tag})
        for overlay in posés:
            if overlay["kind"] not in ("markers", "lines", "text", "ellipses", "rects"):
                raise ValueError(
                    _t("Unknown overlay kind: {kind!r}").format(kind=overlay["kind"])
                )
        self.overlays = [o for o in self.overlays if o.get("tag") != tag] + posés
        self._changed()
        return posés

    def clear_overlays(self, tag: str | None = None) -> None:
        """Clear the overlays; ``tag`` restricts to the overlays bearing that label."""
        if tag is None:
            self.overlays = []
        else:
            self.overlays = [o for o in self.overlays if o.get("tag") != tag]
        self._changed()

    # --- serialization ---------------------------------------------------------
    def to_dict(self) -> dict:
        """Display state as JSON — the form the snapshot already publishes to the frontend.

        ``vw``/``vh``/``dpr`` are **deliberately absent**: they are not a setting but the
        widget's geometry, which the client reports on every mount. Restoring them from a
        project would impose yesterday's window dimensions on today's, and the first
        ``update_geometry`` would overwrite them anyway.
        """
        return {
            "zoom": float(self.zoom),
            "center": list(self.center),
            "channel": self.display_channel,
            "stf_enabled": bool(self.stf_enabled),
            "interaction_mode": self.interaction_mode.value,
            "mask_display_mode": self.mask_display_mode.value,
            "mask_visible": bool(self.mask_visible),
            "transparency_mode": self.transparency_mode.value,
            "overlays": self.overlays,
            "readout": self.readout.to_dict(),
        }

    def apply_dict(self, data: dict) -> None:
        """Reinstall a state produced by :meth:`to_dict`.

        Tolerant: an absent key leaves the value in place, and an invalid value (a channel or
        mode from a newer Retina) is ignored rather than failing the opening of an entire
        project. A single ``on_change`` notification at the end — setting ten fields would
        fire ten, hence ten re-renders.
        """
        if "zoom" in data:
            self.zoom = float(min(max(float(data["zoom"]), _MIN_ZOOM), _MAX_ZOOM))
        if "center" in data:
            cx, cy = data["center"]
            self.center = (float(cx), float(cy))
        if data.get("channel") in DISPLAY_CHANNELS:
            self.display_channel = data["channel"]
        if "stf_enabled" in data:
            self.stf_enabled = bool(data["stf_enabled"])
        for key, enum_, attribut in (
            ("interaction_mode", InteractionMode, "interaction_mode"),
            ("mask_display_mode", MaskDisplayMode, "mask_display_mode"),
            ("transparency_mode", TransparencyMode, "transparency_mode"),
        ):
            if key in data:
                # A mode from a newer Retina leaves the value in place rather than failing
                # the opening of the entire project.
                with contextlib.suppress(ValueError):
                    setattr(self, attribut, enum_(data[key]))
        if "mask_visible" in data:
            self.mask_visible = bool(data["mask_visible"])
        if "readout" in data:
            self.readout = ReadoutOptions.from_dict(data["readout"])
        if "overlays" in data:
            self.overlays = [dict(o) for o in data["overlays"]]
        self._changed()

    def __repr__(self) -> str:
        return (
            f"ViewportState(zoom={self.zoom:g}, center={self.center}, "
            f"channel={self.display_channel!r}, mode={self.interaction_mode.value})"
        )
