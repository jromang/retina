"""Mask generation from an intensity range (RangeSelection) and from a hue range."""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class SatelliteTrailDetection(Process):
    """Detects a linear trail (satellite/aircraft) by Radon transform → mask.

    Isolates the high frequencies and projects in Radon space: a straight line forms a single
    peak ``(rho, theta)`` there. The backprojection (unfiltered iradon) of that peak
    reconstructs the line, thickened by ``width`` pixels → mask (NEW window). The detected
    angle is stored in ``.angle_deg``.
    """

    process_id = "SatelliteTrailDetection"
    category = "MaskGeneration"
    creates_window = True
    is_maskable = False
    parameters = [
        Parameter("threshold", "real", 0.5, 0.05, 0.99, label=N_("Threshold (fraction of peak)")),
        Parameter("width", "int", 2, 0, 30, label=N_("Mask thickness (px)")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.angle_deg: float | None = None

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from scipy.ndimage import binary_dilation, median_filter
        from skimage.transform import iradon, radon

        h, w = data.shape[:2]
        lum = data.mean(axis=2) if data.shape[2] > 1 else data[:, :, 0]
        hp = np.clip(lum - median_filter(lum, size=5, mode="reflect"), 0.0, None)

        theta = np.linspace(0.0, 180.0, 180, endpoint=False)
        sino = radon(hp, theta=theta, circle=False)
        r0, t0 = np.unravel_index(int(np.argmax(sino)), sino.shape)
        self.angle_deg = float(theta[t0])

        peak = np.zeros_like(sino)
        peak[r0, t0] = 1.0  # point↔line duality: backprojecting the peak = drawing the line
        size = sino.shape[0]
        recon = iradon(peak, theta=theta, filter_name=None, circle=False, output_size=size)
        oy, ox = max(0, (recon.shape[0] - h) // 2), max(0, (recon.shape[1] - w) // 2)
        recon = recon[oy:oy + h, ox:ox + w]
        if recon.shape != (h, w):  # cropping safeguard
            fixed = np.zeros((h, w), dtype=recon.dtype)
            fixed[:recon.shape[0], :recon.shape[1]] = recon
            recon = fixed

        peak_val = float(recon.max()) or 1.0
        mask = recon >= self.threshold * peak_val
        if self.width > 0 and mask.any():
            mask = binary_dilation(mask, iterations=int(self.width))
        return mask.astype(np.float32)[:, :, None]


@register
class RangeSelection(Process):
    """Mask (1 channel) from an intensity range over the luminance.

    Pixels whose luminance ∈ [lower, upper] → 1, otherwise 0, with a gradient of width
    ``fuzziness`` at the edges and an optional Gaussian smoothing. Produces a NEW window
    (like StarMask), non-destructive.
    """

    process_id = "RangeSelection"
    category = "MaskGeneration"
    creates_window = True
    is_maskable = False
    parameters = [
        Parameter("lower", "real", 0.0, 0.0, 1.0, label=N_("Lower bound")),
        Parameter("upper", "real", 1.0, 0.0, 1.0, label=N_("Upper bound")),
        Parameter("fuzziness", "real", 0.0, 0.0, 1.0, label=N_("Fuzziness")),
        Parameter("smoothness", "real", 0.0, 0.0, 50.0, label=N_("Smoothness (σ)")),
        Parameter("invert", "bool", False, label=N_("Invert")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        lum = data.mean(axis=2) if data.shape[2] > 1 else data[:, :, 0]
        lo, hi = float(self.lower), float(self.upper)
        f = float(self.fuzziness)
        if f <= 0.0:
            mask = ((lum >= lo) & (lum <= hi)).astype(np.float32)
        else:  # linear ramps of width f on either side of the range
            below = np.clip((lum - (lo - f)) / f, 0.0, 1.0)
            above = np.clip(((hi + f) - lum) / f, 0.0, 1.0)
            mask = np.clip(np.minimum(below, above), 0.0, 1.0).astype(np.float32)
        if self.smoothness > 0.0:
            from scipy.ndimage import gaussian_filter

            mask = gaussian_filter(mask, sigma=float(self.smoothness))
        if self.invert:
            mask = 1.0 - mask
        return np.clip(mask, 0.0, 1.0)[:, :, None].astype(np.float32)


@register
class ColorMask(Process):
    """Mask (1 channel) selecting a **range of hues** — the chromatic counterpart of
    :class:`RangeSelection`, which can only select intensities.

    What it is for: strengthening the Hα regions of a nebula without touching the rest,
    correcting the green cast of stars, desaturating a blue halo. These are gestures a
    luminance mask cannot perform, hue having nothing to do with lightness.

    Two pitfalls the parameterization must handle, and does:

    - **hue is circular.** Red sits both at 0° and at 360°, so a range "from 340 to 20" must
      pass through zero. Naively comparing ``h >= min and h <= max`` would select nothing —
      precisely for the most requested color.
    - **a hue without saturation does not exist.** For a gray pixel, the hue is a rounding
      artifact: it can be anything. Hence ``min_saturation``.

    And a third one, which surprises: over a **dark background**, ``min_saturation`` protects
    against nothing. HSV saturation is a *ratio* — ``(max − min) / max`` — so a sky background
    at 0.06 with 0.01 of noise shows a saturation of 0.4, as "colored" as a solid patch. It is
    ``min_lightness`` that excludes the background, not the saturation. The two guards
    therefore do not do the same job, and both are often needed.
    """

    process_id = "ColorMask"
    category = "MaskGeneration"
    creates_window = True
    is_maskable = False
    parameters = [
        Parameter("hue_center", "real", 0.0, 0.0, 360.0, label=N_("Hue centre (degrees)")),
        Parameter("hue_width", "real", 30.0, 0.1, 180.0, label=N_("Hue half-width (degrees)")),
        Parameter("fuzziness", "real", 15.0, 0.0, 180.0,
                  label=N_("Hue fuzziness (degrees)")),
        Parameter("min_saturation", "real", 0.1, 0.0, 1.0, label=N_("Minimum saturation")),
        Parameter("min_lightness", "real", 0.0, 0.0, 1.0, label=N_("Minimum lightness")),
        Parameter("max_lightness", "real", 1.0, 0.0, 1.0, label=N_("Maximum lightness")),
        Parameter("smoothness", "real", 0.0, 0.0, 50.0, label=N_("Smoothness (σ)")),
        Parameter("invert", "bool", False, label=N_("Invert")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.color import rgb2hsv

        if data.shape[2] < 3:
            raise ValueError(_t("ColorMask requires a color (RGB) image."))
        hsv = rgb2hsv(np.clip(data[:, :, :3], 0.0, 1.0))
        hue = hsv[:, :, 0] * 360.0
        saturation, lightness = hsv[:, :, 1], hsv[:, :, 2]

        # Circular distance to the target hue: this is what closes the circle back on red.
        deviation = np.abs(hue - float(self.hue_center)) % 360.0
        deviation = np.minimum(deviation, 360.0 - deviation)

        half = float(self.hue_width)
        blurred = float(self.fuzziness)
        if blurred <= 0.0:
            mask = (deviation <= half).astype(np.float32)
        else:  # linear ramp beyond the half-width
            mask = np.clip((half + blurred - deviation) / blurred, 0.0, 1.0).astype(np.float32)

        mask *= (saturation >= float(self.min_saturation))
        mask *= (lightness >= float(self.min_lightness)) & (lightness <= float(self.max_lightness))

        if self.smoothness > 0.0:
            from scipy.ndimage import gaussian_filter

            mask = gaussian_filter(mask, sigma=float(self.smoothness))
        if self.invert:
            mask = 1.0 - mask
        return np.clip(mask, 0.0, 1.0)[:, :, None].astype(np.float32)
