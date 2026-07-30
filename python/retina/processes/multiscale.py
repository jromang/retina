"""Multiscale transforms (starlet / à-trous) + local equalization.

`MultiscaleLinearTransform` = the "starlet" wavelet transform (à trous, B3-spline kernel):
decomposes the image into N detail layers + a residual, allows acting scale by scale
(bias/attenuation, noise thresholding), then reconstructs. The basis of denoising and of
structure enhancement. Pure numpy/scipy.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register

_B3 = np.array([1, 4, 6, 4, 1], dtype=np.float64) / 16.0


def _atrous_convolve(img: np.ndarray, step: int) -> np.ndarray:
    from scipy.ndimage import convolve1d

    dil = np.zeros((len(_B3) - 1) * step + 1)
    dil[::step] = _B3  # dilated kernel (holes)
    out = convolve1d(img, dil, axis=0, mode="reflect")
    return convolve1d(out, dil, axis=1, mode="reflect")


def starlet_transform(img: np.ndarray, scales: int):
    """Starlet decomposition: returns (details[j], residual). Reconstruction = sum."""
    c = img.astype(np.float64)
    details = []
    for j in range(scales):
        c_next = _atrous_convolve(c, 2**j)
        details.append(c - c_next)
        c = c_next
    return details, c


@register
class MultiscaleLinearTransform(Process):
    process_id = "MultiscaleLinearTransform"
    category = "MultiscaleProcessing"
    parameters = [
        Parameter("scales", "int", 5, 1, 12, label=N_("Number of scales")),
        # multiplier per scale (console); empty → all at 1 (faithful reconstruction)
        Parameter("bias", "floatlist", default=[], label=N_("Bias per scale")),
        Parameter("noise_threshold", "real", 0.0, 0.0, 10.0,
                  label=N_("Noise threshold (σ, scale 1)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from astropy.stats import mad_std

        J = int(self.scales)
        out = np.empty_like(data)
        for ch in range(data.shape[2]):
            details, residual = starlet_transform(data[:, :, ch], J)
            for j in range(J):
                w = details[j]
                if j == 0 and self.noise_threshold > 0.0:  # denoising: soft-threshold
                    t = self.noise_threshold * mad_std(w)
                    w = np.sign(w) * np.maximum(np.abs(w) - t, 0.0)
                b = self.bias[j] if j < len(self.bias) else 1.0
                details[j] = w * b
            out[:, :, ch] = sum(details) + residual
        return np.clip(out, 0.0, 1.0).astype(np.float32)


def _median_atrous(img: np.ndarray, step: int) -> np.ndarray:
    """Median filter with an à-trous (dilated) window — the core of the median transform."""
    from scipy.ndimage import median_filter

    size = 2 * step + 1
    fp = np.zeros((size, size), dtype=bool)
    fp[::step, ::step] = True  # à-trous sampling of the support
    return median_filter(img, footprint=fp, mode="reflect")


@register
class MultiscaleMedianTransform(Process):
    """Multiscale Median Transform (MMT): nonlinear decomposition by medians.

    Like MLT but with a median filter at each scale → preserves edges and small structures
    better (fewer ringing artifacts). Useful for denoising/enhancement.
    """

    process_id = "MultiscaleMedianTransform"
    category = "MultiscaleProcessing"
    parameters = [
        Parameter("scales", "int", 4, 1, 10, label=N_("Number of scales")),
        Parameter("bias", "floatlist", default=[], label=N_("Bias per scale")),
        Parameter("noise_threshold", "real", 0.0, 0.0, 10.0,
                  label=N_("Noise threshold (σ, scale 1)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from astropy.stats import mad_std

        J = int(self.scales)
        out = np.empty_like(data)
        for ch in range(data.shape[2]):
            c = data[:, :, ch].astype(np.float64)
            details = []
            for j in range(J):
                c_next = _median_atrous(c, 2**j)
                details.append(c - c_next)
                c = c_next
            for j in range(J):
                w = details[j]
                if j == 0 and self.noise_threshold > 0.0:
                    t = self.noise_threshold * mad_std(w)
                    w = np.sign(w) * np.maximum(np.abs(w) - t, 0.0)
                b = self.bias[j] if j < len(self.bias) else 1.0
                details[j] = w * b
            out[:, :, ch] = sum(details) + c
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class HDRMultiscaleTransform(Process):
    """HDR Multiscale Transform (HDRMT): compresses dynamic range by equalizing the scales.

    Decomposes into a starlet, attenuates the residual (large scales = global dynamic range)
    while preserving the detail layers → simultaneously reveals bright cores and faint
    extensions (galaxy/nebula cores). Reuses ``starlet_transform``.
    """

    process_id = "HDRMultiscaleTransform"
    category = "MultiscaleProcessing"
    parameters = [
        Parameter("layers", "int", 6, 2, 12, label=N_("Number of layers")),
        Parameter("overdrive", "real", 0.0, 0.0, 1.0, label=N_("Overdrive (contrast)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        J = int(self.layers)
        out = np.empty_like(data)
        for ch in range(data.shape[2]):
            details, residual = starlet_transform(data[:, :, ch], J)
            # compression: the residual (global dynamic range) is heavily flattened
            r = residual - residual.min()
            rng = float(r.max()) or 1.0
            r = (r / rng) ** (1.0 - 0.5 * self.overdrive)
            recon = sum(details) + r * rng + residual.min()
            lo, hi = float(recon.min()), float(recon.max())
            out[:, :, ch] = (recon - lo) / (hi - lo) if hi > lo else recon
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class MultiscaleAdaptiveStretch(Process):
    """Multiscale adaptive stretch: global tonality stretched, local detail preserved.

    Decomposes the image into a starlet (``layers`` detail layers + a large-scale residual),
    applies **AdaptiveStretch** to the large-scale component alone (the tonality, derived from
    the data) then adds back the detail layers weighted by ``detail_boost`` → reveals faint
    extensions without crushing the highlights or destroying local contrast (a multiscale
    variant of AdaptiveStretch).
    """

    process_id = "MultiscaleAdaptiveStretch"
    category = "MultiscaleProcessing"
    parameters = [
        Parameter("layers", "int", 5, 1, 10, label=N_("Preserved detail layers")),
        Parameter("noise_threshold", "real", 1e-3, 1e-6, 0.5, label=N_("Noise threshold")),
        Parameter("contrast_protection", "real", 0.0, 0.0, 1.0,
                  label=N_("Contrast protection")),
        Parameter("detail_boost", "real", 1.0, 0.0, 4.0, label=N_("Detail boost")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from .stretch import adaptive_stretch_channel

        J = int(self.layers)
        nt = float(self.noise_threshold)
        cp = float(self.contrast_protection)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            details, residual = starlet_transform(data[:, :, c], J)
            # adaptively stretch the tonality (large-scale residual), within [0,1]
            r = residual - residual.min()
            rng = float(r.max()) or 1.0
            stretched = adaptive_stretch_channel(r / rng, nt, cp, 4096) * rng + residual.min()
            recon = stretched + self.detail_boost * sum(details)
            out[:, :, c] = recon
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class RickerWaveletEnhance(Process):
    """Multiscale "Mexican hat" enhancement (Ricker/Marr, astropy).

    Convolves each channel with a 2D Ricker kernel of width ``width`` (band-pass response:
    accentuates structures at that scale, attenuates the background and very fine noise) and
    adds it to the image with weight ``amount``. Ideal for revealing nebulosity and filaments.
    """

    process_id = "RickerWaveletEnhance"
    category = "MultiscaleProcessing"
    parameters = [
        Parameter("width", "real", 2.0, 0.5, 50.0, label=N_("Scale width (σ)")),
        Parameter("amount", "real", 1.0, 0.0, 10.0, label=N_("Amount")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from astropy.convolution import RickerWavelet2DKernel, convolve

        kernel = RickerWavelet2DKernel(float(self.width))
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            detail = convolve(data[:, :, c], kernel, normalize_kernel=False)
            out[:, :, c] = data[:, :, c] + self.amount * detail
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class LocalHistogramEqualization(Process):
    """Contrast-limited adaptive local histogram equalization (CLAHE, scikit-image)."""

    process_id = "LocalHistogramEqualization"
    category = "MultiscaleProcessing"
    parameters = [
        Parameter("clip_limit", "real", 0.01, 0.0, 1.0, label=N_("Clip limit")),
        Parameter("kernel_size", "int", 0, 0, 1024, label=N_("Kernel size (0 = auto)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.exposure import equalize_adapthist

        ks = int(self.kernel_size) or None
        out = np.empty_like(data)
        for ch in range(data.shape[2]):
            src = np.clip(data[:, :, ch], 0.0, 1.0)
            out[:, :, ch] = equalize_adapthist(src, kernel_size=ks, clip_limit=self.clip_limit)
        return out.astype(np.float32)
