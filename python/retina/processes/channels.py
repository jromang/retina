"""Trivial channel/pixel processes (pure numpy) — high value, zero cost."""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register

_LUMA = (0.2126, 0.7152, 0.0722)


@register
class ChannelExtraction(Process):
    process_id = "ChannelExtraction"
    category = "ColorSpaces"
    parameters = [
        Parameter("channel", "enum", "L", choices=("R", "G", "B", "L"), label=N_("Channel")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] == 1:
            return data.copy()
        if self.channel == "L":
            lum = sum(w * data[:, :, i] for i, w in enumerate(_LUMA))
            return lum[:, :, None].astype(np.float32)
        idx = {"R": 0, "G": 1, "B": 2}[self.channel]
        return data[:, :, idx : idx + 1].copy()


@register
class ChannelCombination(Process):
    """Combines three views (by id) into RGB. An empty channel reuses the current image."""

    process_id = "ChannelCombination"
    category = "ColorSpaces"
    parameters = [
        Parameter("r", "str", "", label=N_("R view")),
        Parameter("g", "str", "", label=N_("G view")),
        Parameter("b", "str", "", label=N_("B view")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from ..process import context

        base = data[:, :, 0]

        def ch(identifier: str) -> np.ndarray:
            if not identifier:
                return base
            arr = context.resolve_image_full(identifier)
            return arr[:, :, 0] if arr is not None else base

        return np.dstack([ch(self.r), ch(self.g), ch(self.b)]).astype(np.float32)


@register
class Invert(Process):
    process_id = "Invert"
    category = "PixelMath"
    parameters = []

    def _apply(self, data: np.ndarray) -> np.ndarray:
        return (1.0 - data).astype(np.float32)


@register
class Rescale(Process):
    process_id = "Rescale"
    category = "IntensityTransformations"
    parameters = [
        Parameter("low", "real", 0.0, 0.0, 1.0, label=N_("Lower bound")),
        Parameter("high", "real", 1.0, 0.0, 1.0, label=N_("Upper bound")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        lo, hi = float(data.min()), float(data.max())
        y = (data - lo) / (hi - lo) if hi > lo else np.zeros_like(data)
        return (y * (self.high - self.low) + self.low).astype(np.float32)


@register
class Binarize(Process):
    process_id = "Binarize"
    category = "IntensityTransformations"
    parameters = [Parameter("threshold", "real", 0.5, 0.0, 1.0, label=N_("Threshold"))]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        return (data >= self.threshold).astype(np.float32)


@register
class ChannelMatch(Process):
    """Fine channel registration: subpixel translation and linear factor per channel.

    The tool for color fringes — lateral chromatic aberration, drift between filters on a
    poorly guided mount. The model is a (dx, dy) offset and a multiplicative factor per
    channel, with spline interpolation (``scipy.ndimage.shift``). On a single-channel image,
    a documented no-op.
    """

    process_id = "ChannelMatch"
    category = "Geometry"
    parameters = [
        Parameter("dx", "floatlist", default=[0.0, 0.0, 0.0], label=N_("X offsets (px)")),
        Parameter("dy", "floatlist", default=[0.0, 0.0, 0.0], label=N_("Y offsets (px)")),
        Parameter("factors", "floatlist", default=[1.0, 1.0, 1.0],
                  label=N_("Linear correction factors")),
        Parameter("order", "int", 3, 0, 5, label=N_("Interpolation order")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] == 1:
            return data.copy()
        from scipy import ndimage

        def value(items, index: int, default: float) -> float:
            return float(items[index]) if index < len(items) else default

        out = np.empty_like(data)
        for c in range(data.shape[2]):
            dx = value(self.dx, c, 0.0)
            dy = value(self.dy, c, 0.0)
            factor = value(self.factors, c, 1.0)
            plane = data[:, :, c]
            if dx or dy:
                # shift moves the content by +dy/+dx along the (y, x) axes; the uncovered
                # border stays at 0, as after a StarAlignment
                plane = ndimage.shift(plane.astype(np.float64), (dy, dx),
                                      order=int(self.order), mode="constant", cval=0.0)
            out[:, :, c] = plane * factor
        return np.clip(out, 0.0, 1.0).astype(np.float32)
