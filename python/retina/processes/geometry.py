"""Geometry: Crop, Resample, IntegerResample, Rotation, FastRotation.

Thin scikit-image / scipy / numpy wrappers. All of them change the geometry →
``is_maskable = False`` (mask blending, which assumes an identical shape, does not apply).
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class AutoCrop(Process):
    """Removes the incomplete borders of an integrated image.

    After registration, the exposures do not overlap exactly — that is the very principle of
    dithering. The borders of the integration therefore receive only a fraction of the frames,
    when they receive any at all: there one finds zero fill, a collapsed signal-to-noise ratio,
    and values that skew both the automatic stretch and the statistics. That is why cropping is
    the default in automated pre-processing.

    Coverage is measured on the **registered frames**, not on the integration: in the latter, a
    border seen by half the exposures is not zero, only attenuated — so it would go unnoticed,
    and that is precisely the case we want to eliminate. Hence ``frames``. Without that list we
    fall back on the only test possible from an isolated image — exactly-zero pixels — which
    detects only the borders seen by *no* exposure.

    The rule is deliberately simple and free of surprises: an edge row or column is trimmed as
    long as it holds less than ``coverage`` of covered pixels, stopping as soon as a complete
    row appears. We do not look for the largest possible rectangle — that would be an
    optimization problem whose result would surprise, whereas here the lost area is the
    dithering area, and it lies along the border by construction.
    """

    process_id = "AutoCrop"
    category = "Geometry"
    is_maskable = False
    parameters = [
        Parameter("coverage", "real", 0.98, 0.0, 1.0, label=N_("Required coverage"),
                  tooltip=N_("Minimum fraction of non-zero pixels to keep a row")),
        Parameter("max_fraction", "real", 0.25, 0.0, 0.9, label=N_("Maximum trim"),
                  tooltip=N_("Safeguard: beyond this, a legitimately dark image is suspected")),
        Parameter("frames", "pathlist", [], label=N_("Registered frames"),
                  tooltip=N_("Used to measure the actual coverage; empty = inferred from the "
                             "image")),
    ]

    def _covered(self, data: np.ndarray) -> np.ndarray:
        """Fraction of exposures that contributed to each pixel, within ``[0, 1]``."""
        if not self.frames:
            return (np.abs(data).max(axis=2) > 0.0).astype(np.float32)
        from ..io import open_lazy

        total = np.zeros(data.shape[:2], dtype=np.float32)
        for path in self.frames:
            with open_lazy(path) as image:
                if image.shape[:2] != data.shape[:2]:
                    # unexpected geometry: better not to trim than to trim wrongly
                    return np.ones(data.shape[:2], dtype=np.float32)
                total += (np.abs(image.band(0, image.shape[0])).max(axis=2) > 0.0)
        return total / len(self.frames)

    def bounds(self, data: np.ndarray) -> tuple[int, int, int, int]:
        """``(y0, y1, x0, x1)`` of the kept area — exposed for inspection.

        The trimming is **iterative**, and it has to be: a single empty column drops the
        coverage of *every* row below the threshold. Evaluating rows and columns once and for
        all over the whole image would therefore trim far beyond what is necessary. So the
        least-covered edge is removed, the computation is redone over the remaining rectangle,
        and it stops as soon as all four edges are complete.
        """
        filled = self._covered(data) >= 1.0 - 1e-6
        height, width = filled.shape
        threshold = float(self.coverage)
        limit_y = int(height * float(self.max_fraction))
        limit_x = int(width * float(self.max_fraction))
        y0, y1, x0, x1 = 0, height, 0, width

        while y1 - y0 > 1 and x1 - x0 > 1:
            view = filled[y0:y1, x0:x1]
            # The second tuple element breaks ties, and it is a rank rather than the side
            # name on purpose: `min()` on a name would let the alphabet decide which edge is
            # trimmed first, so translating the names would silently change the result on an
            # exact tie. The ranks below reproduce the order that was in force.
            edges = []
            if y0 < limit_y:
                edges.append((float(view[0].mean()), 3, "top"))
            if height - y1 < limit_y:
                edges.append((float(view[-1].mean()), 0, "bottom"))
            if x0 < limit_x:
                edges.append((float(view[:, 0].mean()), 2, "left"))
            if width - x1 < limit_x:
                edges.append((float(view[:, -1].mean()), 1, "right"))
            candidates = [b for b in edges if b[0] < threshold]
            if not candidates:
                break
            _, _, side = min(candidates)
            if side == "top":
                y0 += 1
            elif side == "bottom":
                y1 -= 1
            elif side == "left":
                x0 += 1
            else:
                x1 -= 1

        # an entirely trimmed image makes no sense: return the original
        if y1 - y0 < 1 or x1 - x0 < 1:
            return (0, height, 0, width)
        return (y0, y1, x0, x1)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        y0, y1, x0, x1 = self.bounds(data)
        return np.ascontiguousarray(data[y0:y1, x0:x1, :])


@register
class Crop(Process):
    """Crops to fractional bounds in ``[0,1]`` — (x0,y0) = top-left corner."""

    process_id = "Crop"
    category = "Geometry"
    is_maskable = False
    parameters = [
        Parameter("x0", "real", 0.0, 0.0, 1.0, label=N_("Left")),
        Parameter("y0", "real", 0.0, 0.0, 1.0, label=N_("Top")),
        Parameter("x1", "real", 1.0, 0.0, 1.0, label=N_("Right")),
        Parameter("y1", "real", 1.0, 0.0, 1.0, label=N_("Bottom")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        h, w = data.shape[:2]
        x0 = int(round(min(self.x0, self.x1) * w))
        x1 = int(round(max(self.x0, self.x1) * w))
        y0 = int(round(min(self.y0, self.y1) * h))
        y1 = int(round(max(self.y0, self.y1) * h))
        x1 = max(x1, x0 + 1)
        y1 = max(y1, y0 + 1)
        return data[y0:y1, x0:x1, :].copy()


@register
class Resample(Process):
    """Resamples by a scale factor (interpolation)."""

    process_id = "Resample"
    category = "Geometry"
    is_maskable = False
    parameters = [
        Parameter("scale", "real", 0.5, 0.01, 20.0, label=N_("Scale factor")),
        Parameter("order", "int", 1, 0, 5, label=N_("Interpolation order")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.transform import resize

        h, w = data.shape[:2]
        nh = max(1, int(round(h * self.scale)))
        nw = max(1, int(round(w * self.scale)))
        out = resize(data, (nh, nw, data.shape[2]), order=int(self.order),
                     mode="reflect", anti_aliasing=self.scale < 1.0)
        return out.astype(np.float32)


@register
class IntegerResample(Process):
    """Downscaling/upscaling by an integer factor (averaged binning or replication)."""

    process_id = "IntegerResample"
    category = "Geometry"
    is_maskable = False
    parameters = [
        Parameter("factor", "int", 2, 1, 16, label=N_("Integer factor")),
        Parameter("mode", "enum", "downsample",
                  choices=("downsample", "upsample"), label=N_("Direction")),
        Parameter("downsample_op", "enum", "average", choices=("average", "sum"),
                  label=N_("Binning (average / sum = flux preserving)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        n = max(1, int(self.factor))
        if n == 1:
            return data.copy()
        if self.mode == "upsample":
            return np.repeat(np.repeat(data, n, axis=0), n, axis=1).astype(np.float32)
        if self.downsample_op == "sum":
            # flux-preserving binning (astropy block_reduce, func=sum): the sum of the
            # counts is preserved — the correct route for photometric data.
            from astropy.nddata import block_reduce

            binned = block_reduce(data, (n, n, 1), func=np.sum)
            return np.clip(binned, 0.0, 1.0).astype(np.float32)
        h, w, c = data.shape
        hh, ww = (h // n) * n, (w // n) * n  # crop to the multiple
        cropped = data[:hh, :ww, :]
        binned = cropped.reshape(hh // n, n, ww // n, n, c).mean(axis=(1, 3))
        return binned.astype(np.float32)


@register
class Rotation(Process):
    """Rotation by an arbitrary angle (degrees); the image is enlarged to contain it all."""

    process_id = "Rotation"
    category = "Geometry"
    is_maskable = False
    parameters = [
        Parameter("angle", "real", 0.0, -360.0, 360.0, label=N_("Angle (°)")),
        Parameter("order", "int", 1, 0, 5, label=N_("Interpolation order")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from scipy.ndimage import rotate

        out = rotate(data, angle=float(self.angle), axes=(0, 1), reshape=True,
                     order=int(self.order), mode="constant", cval=0.0)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class FastRotation(Process):
    """Lossless rotations by multiples of 90° and mirrors (numpy)."""

    process_id = "FastRotation"
    category = "Geometry"
    is_maskable = False
    parameters = [
        Parameter("operation", "enum", "rotate90",
                  choices=("rotate90", "rotate180", "rotate270", "hmirror", "vmirror"),
                  label=N_("Operation")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        op = self.operation
        if op == "rotate90":
            out = np.rot90(data, k=1, axes=(0, 1))
        elif op == "rotate180":
            out = np.rot90(data, k=2, axes=(0, 1))
        elif op == "rotate270":
            out = np.rot90(data, k=3, axes=(0, 1))
        elif op == "hmirror":
            out = data[:, ::-1, :]
        else:  # vmirror
            out = data[::-1, :, :]
        return np.ascontiguousarray(out, dtype=np.float32)
