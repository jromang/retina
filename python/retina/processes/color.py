"""Color processes: SCNR, grayscale/RGB conversions, saturation, channel adjustment.

Thin numpy / scikit-image wrappers (`SCNR`, `ConvertToGrayscale/RGBColor`, `ColorSaturation`,
`LinearFit`, `ColorCalibration`, `LRGBCombination`, `RGBWorkingSpace`). Heavy imports are lazy.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register

_LUMA = (0.2126, 0.7152, 0.0722)


@register
class SCNR(Process):
    """Subtractive Chromatic Noise Reduction — removes the green cast (or another channel).

    Standard "neutral" protection: the target channel is capped by a neutral reference computed
    from the two other channels (average or maximum). ``amount`` blends the result with the
    original.
    """

    process_id = "SCNR"
    category = "ColorCalibration"
    parameters = [
        Parameter("channel", "enum", "G", choices=("R", "G", "B"), label=N_("Channel")),
        Parameter("protection", "enum", "average",
                  choices=("average", "maximum"), label=N_("Neutral protection")),
        Parameter("amount", "real", 1.0, 0.0, 1.0, label=N_("Amount")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 3:
            return data.copy()
        idx = {"R": 0, "G": 1, "B": 2}[self.channel]
        others = [i for i in range(3) if i != idx]
        a, b = data[:, :, others[0]], data[:, :, others[1]]
        neutral = (a + b) * 0.5 if self.protection == "average" else np.maximum(a, b)
        target = data[:, :, idx]
        capped = np.minimum(target, neutral)
        out = data.copy()
        out[:, :, idx] = target + self.amount * (capped - target)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class ConvertToGrayscale(Process):
    """Converts an RGB image to grayscale (weighted luminance)."""

    process_id = "ConvertToGrayscale"
    category = "ColorSpaces"
    is_maskable = False  # changes the number of channels
    parameters = []

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] == 1:
            return data.copy()
        lum = sum(w * data[:, :, i] for i, w in enumerate(_LUMA))
        return lum[:, :, None].astype(np.float32)


@register
class ConvertToRGBColor(Process):
    """Converts a grayscale image to RGB (replicated channels)."""

    process_id = "ConvertToRGBColor"
    category = "ColorSpaces"
    is_maskable = False
    parameters = []

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] >= 3:
            return data.copy()
        return np.repeat(data[:, :, :1], 3, axis=2).astype(np.float32)


@register
class HistogramMatching(Process):
    """Aligns the intensity distribution on a reference view (skimage).

    ``match_histograms`` reproduces the cumulative histogram of the reference → normalizes the
    background and the color across frames before mosaicking/integration. Without a valid
    reference, the image is returned unchanged.
    """

    process_id = "HistogramMatching"
    category = "ColorCalibration"
    parameters = [Parameter("reference", "str", "", label=N_("Reference view"))]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.exposure import match_histograms

        from ..process import context

        if not self.reference:
            return data.copy()
        ref = context.resolve_image_full(self.reference)
        if ref is None:
            return data.copy()
        # match channel by channel if the channel geometries differ
        if ref.shape[2] == data.shape[2]:
            out = match_histograms(data, ref, channel_axis=-1)
        else:
            out = np.empty_like(data)
            for c in range(data.shape[2]):
                out[:, :, c] = match_histograms(data[:, :, c], ref[:, :, min(c, ref.shape[2] - 1)])
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class ColorSaturation(Process):
    """Adjusts the saturation (global factor) through the HSV space (scikit-image)."""

    process_id = "ColorSaturation"
    category = "IntensityTransformations"
    parameters = [
        Parameter("saturation", "real", 1.5, 0.0, 5.0, label=N_("Saturation")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 3:
            return data.copy()
        from skimage.color import hsv2rgb, rgb2hsv

        hsv = rgb2hsv(np.clip(data[:, :, :3], 0.0, 1.0))
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * self.saturation, 0.0, 1.0)
        rgb = hsv2rgb(hsv).astype(np.float32)
        if data.shape[2] > 3:  # preserves any extra channels
            out = data.copy()
            out[:, :, :3] = rgb
            return out
        return rgb


@register
class LinearFit(Process):
    """Linearly fits each channel to a reference view (least squares).

    ``out = a·in + b`` per channel, where (a, b) minimize the deviation from the reference.
    Used to equalize channels/panels before combination or mosaicking.
    """

    process_id = "LinearFit"
    category = "ColorCalibration"
    parameters = [Parameter("reference", "str", "", label=N_("Reference view"))]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from ..process import context

        if not self.reference:
            return data.copy()
        ref = context.resolve_image_full(self.reference)
        if ref is None:
            return data.copy()
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            rc = ref[:, :, min(c, ref.shape[2] - 1)].ravel()
            x = data[:, :, c].ravel()
            a, b = np.polyfit(x, rc, 1)
            out[:, :, c] = (a * data[:, :, c] + b)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class ColorCalibration(Process):
    """White balance from reference regions (background + white).

    Neutralizes the background (subtracting the robust per-channel median) then equalizes the
    gains so that a "white" region is neutral. Without an explicit reference preview, the white
    reference = the whole image (gray-world). Reuses ``sigma_clipped_stats``.
    """

    process_id = "ColorCalibration"
    category = "ColorCalibration"
    parameters = [
        Parameter("white_reference", "str", "",
                  label=N_("White preview (empty = gray-world)")),
        Parameter("background_reference", "str", "",
                  label=N_("Background preview (empty = image)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 3:
            return data.copy()
        from astropy.stats import sigma_clipped_stats

        from ..process import context

        def region(identifier: str) -> np.ndarray:
            if identifier:
                arr = context.resolve_image_full(identifier)
                if arr is not None:
                    return arr
            return data

        white = region(self.white_reference)
        out = data.copy()
        # 1) white balance: gains equalizing the means of the white region
        white_means = [max(float(np.mean(white[:, :, c])), 1e-6) for c in range(3)]
        target = float(np.mean(white_means))
        for c in range(3):
            out[:, :, c] = data[:, :, c] * (target / white_means[c])
        # 2) background neutralization: aligns the background medians on the lowest one
        bkg = region(self.background_reference)
        bg_after_gain = bkg if self.background_reference else out
        bg_meds = [sigma_clipped_stats(bg_after_gain[:, :, c], sigma=3.0)[1] for c in range(3)]
        floor = min(bg_meds)
        for c in range(3):
            out[:, :, c] -= (bg_meds[c] - floor)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class LRGBCombination(Process):
    """Combines a luminance (view L) with the current RGB chrominance (L*a*b* space)."""

    process_id = "LRGBCombination"
    category = "ColorSpaces"
    parameters = [
        Parameter("luminance", "str", "", label=N_("Luminance view")),
        Parameter("weight", "real", 1.0, 0.0, 1.0, label=N_("L weight")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 3 or not self.luminance:
            return data.copy()
        from skimage.color import lab2rgb, rgb2lab

        from ..process import context

        larr = context.resolve_image_full(self.luminance)
        if larr is None:
            return data.copy()
        lum = larr[:, :, 0]
        lab = rgb2lab(np.clip(data[:, :, :3], 0.0, 1.0))
        new_l = lum * 100.0  # L* ∈ [0,100]
        lab[:, :, 0] = (1.0 - self.weight) * lab[:, :, 0] + self.weight * new_l
        rgb = np.clip(lab2rgb(lab), 0.0, 1.0).astype(np.float32)
        if data.shape[2] > 3:
            out = data.copy()
            out[:, :, :3] = rgb
            return out
        return rgb


@register
class RGBWorkingSpace(Process):
    """Applies RGB luminance weights (RGB Working Space) — normalizes the luminance.

    A minimal model of an RGB working space: renormalizes each channel by its relative
    luminance weight, which influences the luminance-dependent processes.
    """

    process_id = "RGBWorkingSpace"
    category = "ColorSpaces"
    parameters = [
        Parameter("rw", "real", 0.2126, 0.0, 1.0, label=N_("R weight")),
        Parameter("gw", "real", 0.7152, 0.0, 1.0, label=N_("G weight")),
        Parameter("bw", "real", 0.0722, 0.0, 1.0, label=N_("B weight")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 3:
            return data.copy()
        weights = np.array([self.rw, self.gw, self.bw], dtype=np.float32)
        s = float(weights.sum()) or 1.0
        weights = weights / s
        out = data.copy()
        for c in range(3):
            out[:, :, c] = data[:, :, c] * (weights[c] * 3.0)  # 3×: neutral if weights are equal
        return np.clip(out, 0.0, 1.0).astype(np.float32)
