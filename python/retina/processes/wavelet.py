"""Decimated & undecimated wavelets (PyWavelets).

Complements the à trous starlet (``MultiscaleLinearTransform``) with true orthogonal
wavelets: ``WaveletDenoise`` (undecimated SWT + robust soft thresholding, without
decimation artifacts) and ``WaveletTransform`` (DWT decomposition/reconstruction with
per-scale-band gain). Lazy import of ``pywt``.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


def _pad_to_multiple(ch: np.ndarray, level: int) -> tuple[np.ndarray, tuple[int, int]]:
    """Mirror-pads so that H and W are multiples of ``2**level`` (required by the SWT)."""
    m = 2**level
    h, w = ch.shape
    ph, pw = (-h) % m, (-w) % m
    if ph or pw:
        ch = np.pad(ch, ((0, ph), (0, pw)), mode="reflect")
    return ch, (h, w)


@register
class WaveletDenoise(Process):
    """Denoising by undecimated wavelets (SWT) + robust soft thresholding.

    The stationary transform (translation-invariant) avoids the block artifacts of the
    decimated DWT. Detail coefficients are soft-thresholded at ``k`` times each band's robust
    deviation (MAD). ``wavelet`` = family (db2, sym4, coif1…).
    """

    process_id = "WaveletDenoise"
    category = "NoiseReduction"
    parameters = [
        Parameter("wavelet", "str", "db2", label=N_("Wavelet")),
        Parameter("level", "int", 3, 1, 8, label=N_("Levels")),
        Parameter("threshold", "real", 3.0, 0.0, 20.0, label=N_("Threshold (k × MAD)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import pywt

        level = int(self.level)
        k = float(self.threshold)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            padded, (h, w) = _pad_to_multiple(data[:, :, c].astype(np.float64), level)
            coeffs = pywt.swt2(padded, self.wavelet, level=level, trim_approx=True)
            approx = coeffs[0]
            new_details = []
            for (cH, cV, cD) in coeffs[1:]:
                bands = []
                for band in (cH, cV, cD):
                    sigma = 1.4826 * np.median(np.abs(band - np.median(band))) or 1e-9
                    t = k * sigma
                    bands.append(np.sign(band) * np.maximum(np.abs(band) - t, 0.0))
                new_details.append(tuple(bands))
            rec = pywt.iswt2([approx, *new_details], self.wavelet)
            out[:, :, c] = rec[:h, :w]
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class WaveletTransform(Process):
    """DWT decomposition/reconstruction with per-band gain (``pywt.wavedec2``).

    Decomposes into ``level`` scales, applies ``approx_gain`` to the approximation (low
    frequencies = background/brightness) and ``detail_gain`` to every detail (high frequencies =
    fine structures), then reconstructs. ``detail_gain>1`` sharpens, ``<1`` softens.
    """

    process_id = "WaveletTransform"
    category = "MultiscaleProcessing"
    parameters = [
        Parameter("wavelet", "str", "db2", label=N_("Wavelet")),
        Parameter("level", "int", 3, 1, 8, label=N_("Levels")),
        Parameter("approx_gain", "real", 1.0, 0.0, 5.0, label=N_("Approximation gain")),
        Parameter("detail_gain", "real", 1.0, 0.0, 5.0, label=N_("Detail gain")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import pywt

        level = int(self.level)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            ch = data[:, :, c].astype(np.float64)
            coeffs = pywt.wavedec2(ch, self.wavelet, level=level, mode="reflect")
            coeffs[0] = coeffs[0] * self.approx_gain
            scaled = [coeffs[0]]
            for (cH, cV, cD) in coeffs[1:]:
                g = self.detail_gain
                scaled.append((cH * g, cV * g, cD * g))
            rec = pywt.waverec2(scaled, self.wavelet, mode="reflect")
            out[:, :, c] = rec[:ch.shape[0], :ch.shape[1]]
        return np.clip(out, 0.0, 1.0).astype(np.float32)
