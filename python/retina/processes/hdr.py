"""HDR & fast integration: HDRComposition, FastIntegration (global processes).

HDRComposition combines exposures of different durations while preserving the unsaturated
highlights. FastIntegration = plain stacking without rejection (mean/median), for a quick
preview. numpy / astropy.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def _poisson_solve_neumann(divergence: np.ndarray) -> np.ndarray:
    """Solves ∇²I = div with Neumann boundaries via DCT (gradient-domain reconstruction).

    Diagonalizes the 5-point Laplacian by the DCT-II; the constant (DC mode) is undetermined
    and set to 0. The core shared by gradient-domain HDR composition and compression.
    """
    from scipy.fft import dctn, idctn

    h, w = divergence.shape
    dct = dctn(divergence, norm="ortho")
    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :]
    denom = (2.0 * np.cos(np.pi * yy / h) - 2.0) + (2.0 * np.cos(np.pi * xx / w) - 2.0)
    denom[0, 0] = 1.0  # avoids the division by zero on the constant mode
    res = dct / denom
    res[0, 0] = 0.0
    return idctn(res, norm="ortho")


def _gradients(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Forward gradients (differences), right/bottom edge set to zero."""
    gx = np.zeros_like(img)
    gy = np.zeros_like(img)
    gx[:, :-1] = img[:, 1:] - img[:, :-1]
    gy[:-1, :] = img[1:, :] - img[:-1, :]
    return gx, gy


def _divergence(gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    """Divergence (adjoint of the forward differences) of the field (gx, gy)."""
    div = np.zeros_like(gx)
    div[:, 0] += gx[:, 0]
    div[:, 1:] += gx[:, 1:] - gx[:, :-1]
    div[0, :] += gy[0, :]
    div[1:, :] += gy[1:, :] - gy[:-1, :]
    return div


@register
class GradientHDRCompression(Process):
    """Gradient-domain dynamic range compression (Fattal et al. 2002, simplified).

    Attenuates the **large** gradients of the log-luminance (abrupt core→background
    transitions) while preserving the small ones (local detail), then reconstructs the image by
    solving a Poisson equation. Simultaneously reveals bright nuclei and faint extensions, like
    ``HDRMultiscaleTransform`` but without ringing halos. ``beta`` < 1 = stronger compression.
    """

    process_id = "GradientHDRCompression"
    category = "MultiscaleProcessing"
    parameters = [
        Parameter("beta", "real", 0.85, 0.1, 1.0, label=N_("Exponent (compression, <1)")),
        Parameter("alpha", "real", 0.1, 0.01, 1.0, label=N_("Threshold (× mean gradient)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        beta = float(self.beta)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            log = np.log(np.clip(data[:, :, c], 1e-4, None))
            gx, gy = _gradients(log)
            mag = np.sqrt(gx * gx + gy * gy)
            a = max(self.alpha * float(mag.mean()), 1e-6)
            # attenuation factor Φ: ≈1 for |∇|≤a, compresses beyond it (Fattal)
            phi = np.where(mag > 1e-9, (a / np.maximum(mag, 1e-9)) * (mag / a) ** beta, 1.0)
            recon = _poisson_solve_neumann(_divergence(gx * phi, gy * phi))
            img = np.exp(recon)
            lo, hi = float(img.min()), float(img.max())
            out[:, :, c] = (img - lo) / (hi - lo) if hi > lo else img
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class GradientHDRComposition(Process):
    """Gradient-domain HDR composition (global process, multi-frame).

    At each pixel, keeps the gradient vector of **largest magnitude** among all the exposures
    (the best-exposed detail — sharp core from the short exposures, extensions from the long
    ones), then integrates the merged field by solving a Poisson equation → an image without
    seams or saturation. The exposures must be **registered** (same grid).
    """

    process_id = "GradientHDRComposition"
    category = "ImageIntegration"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Registered frames")),
        Parameter("new_image_id", "str", "gradient_hdr", label=N_("Result id")),
    ]

    def combine(self) -> np.ndarray:
        from ..io import load_image_array

        if not self.frames:
            raise ValueError(_t("GradientHDRComposition: no frames provided"))
        frames = [load_image_array(p).astype(np.float64) for p in self.frames]
        shape = frames[0].shape
        out = np.empty(shape, dtype=np.float32)
        for c in range(shape[2]):
            best_gx = np.zeros(shape[:2])
            best_gy = np.zeros(shape[:2])
            best_mag = np.full(shape[:2], -1.0)
            for f in frames:
                gx, gy = _gradients(np.log(np.clip(f[:, :, c], 1e-4, None)))
                mag = gx * gx + gy * gy
                take = mag > best_mag
                best_gx = np.where(take, gx, best_gx)
                best_gy = np.where(take, gy, best_gy)
                best_mag = np.where(take, mag, best_mag)
            img = np.exp(_poisson_solve_neumann(_divergence(best_gx, best_gy)))
            lo, hi = float(img.min()), float(img.max())
            out[:, :, c] = (img - lo) / (hi - lo) if hi > lo else img
        return np.clip(out, 0.0, 1.0).astype(np.float32)

    def execute_global(self, app) -> bool:
        from ..model.image import Image

        app.new_window(Image(self.combine()), window_id=self.new_image_id or None)
        return True


@register
class HDRComposition(Process):
    """Composes an HDR image from exposures of increasing duration (global process).

    Without exposure metadata, the relative duration of each exposure is estimated from its
    median. Each frame is brought to a common scale; pixels close to saturation are discarded →
    the bright cores (short exposures) and the faint extensions (long exposures) coexist.
    """

    process_id = "HDRComposition"
    category = "ImageIntegration"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Frames (increasing exposure)")),
        Parameter("saturation", "real", 0.9, 0.1, 1.0, label=N_("Saturation threshold")),
        Parameter("new_image_id", "str", "hdr", label=N_("Result id")),
    ]

    def combine(self) -> np.ndarray:
        from ..io import load_image_array

        if not self.frames:
            raise ValueError(_t("HDRComposition: no frames provided"))
        frames = [load_image_array(p).astype(np.float64) for p in self.frames]
        medians = [max(float(np.median(f)), 1e-6) for f in frames]
        ref = max(medians)  # the "longest" exposure serves as the scale reference
        sat = float(self.saturation)
        acc = np.zeros_like(frames[0])
        wsum = np.zeros_like(frames[0])
        for f, med in zip(frames, medians, strict=True):
            scaled = f * (ref / med)
            weight = (f < sat).astype(np.float64)  # discards saturated pixels
            acc += scaled * weight
            wsum += weight
        result = np.where(wsum > 0, acc / np.maximum(wsum, 1e-6), frames[-1])
        hi = float(result.max()) or 1.0
        return (result / hi).astype(np.float32)  # renormalize into [0,1]

    def execute_global(self, app) -> bool:
        from ..model.image import Image

        app.new_window(Image(self.combine()), window_id=self.new_image_id or None)
        return True


@register
class FastIntegration(Process):
    """Fast stacking without rejection (mean or median) — global process.

    A lightweight alternative to ``Integration`` for a preview: no sigma rejection, just a
    direct combination. Useful over many frames when speed matters most.
    """

    process_id = "FastIntegration"
    category = "ImageIntegration"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Frames")),
        Parameter("combine", "enum", "mean", choices=("mean", "median"),
                  label=N_("Combination")),
        Parameter("new_image_id", "str", "fast_integration", label=N_("Result id")),
    ]

    def stack(self) -> np.ndarray:
        from ..io import load_image_array

        if not self.frames:
            raise ValueError(_t("FastIntegration: no frames provided"))
        arr = np.stack([load_image_array(p).astype(np.float32) for p in self.frames], axis=0)
        result = np.median(arr, axis=0) if self.combine == "median" else arr.mean(axis=0)
        return result.astype(np.float32)

    def execute_global(self, app) -> bool:
        from ..model.image import Image

        app.new_window(Image(self.stack()), window_id=self.new_image_id or None)
        return True
