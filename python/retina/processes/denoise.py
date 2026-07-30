"""Specialized denoising: TGVDenoise, ACDNR.

Complements ``NoiseReduction`` (restore.py) with more specialized methods.
scikit-image / scipy. Lazy imports.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


# --- differential operators (Neumann boundaries) for TGV ------------------------
def _tgv_rust():
    """The native pyfunction, or ``None`` — `getattr`: an extension built before
    ``tgv_denoise`` existed must not break the import."""
    try:
        from .. import _core  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - depends on the build
        return None
    return getattr(_core, "tgv_denoise", None)


#: The operators below only do slicing and ufuncs: they therefore run indifferently on numpy
#: or on CuPy, provided the arrays they *allocate* come from the right module. Hence these two
#: factories — that is all it took to port TGV to the GPU.
def _zeros_like(a):
    from ..backend.xp import get_array_module

    return get_array_module(a).zeros_like(a)


def _empty_like(a):
    from ..backend.xp import get_array_module

    return get_array_module(a).empty_like(a)


def _grad_x(u):
    g = _zeros_like(u)
    g[:, :-1] = u[:, 1:] - u[:, :-1]
    return g


def _grad_y(u):
    g = _zeros_like(u)
    g[:-1, :] = u[1:, :] - u[:-1, :]
    return g


def _div_x(p):  # adjoint (up to a sign) of _grad_x: backward difference
    d = _empty_like(p)
    d[:, 0] = p[:, 0]
    d[:, 1:-1] = p[:, 1:-1] - p[:, :-2]
    d[:, -1] = -p[:, -2]
    return d


def _div_y(p):
    d = _empty_like(p)
    d[0, :] = p[0, :]
    d[1:-1, :] = p[1:-1, :] - p[:-2, :]
    d[-1, :] = -p[-2, :]
    return d


def _tgv_denoise_channel(f, alpha1, alpha0, iterations):
    """TGV² denoising (Bredies-Kunisch-Pock) by primal-dual (Chambolle-Pock).

    Minimizes ``½‖u-f‖² + α1‖∇u-w‖₁ + α0‖E(w)‖₁``: the auxiliary field ``w`` absorbs smooth
    ramps → no staircasing effect as in pure TV, while keeping edges sharp. ``E`` = symmetrized
    gradient of ``w``.

    The one hot spot profiling flagged as worth writing in Rust (~229 s at 24 Mpx, 94 % in pure
    Python): the native core ``_core.tgv_denoise`` takes over when present (GIL released,
    parallel by rows, numerical parity tested); this numpy path remains the fallback for
    machines without the compiled extension — and the reference of its parity test.

    **A CuPy array short-circuits the Rust** and takes the same loop, which is made only of
    slicing and ufuncs. The gain is more modest than elsewhere — ×2.7 at 24 Mpx against the
    Rust, where RL gets ×46 — because the algorithm is limited by memory bandwidth rather than
    by compute, and multicore Rust is already good at it. We keep it anyway: twelve seconds
    that become four and a half are felt, and the result is **bit for bit** that of the Rust
    (same operations, same order, float64).
    """
    from ..backend.xp import _is_cupy, get_array_module

    xp = get_array_module(f)
    rust = _tgv_rust() if not _is_cupy(f) else None
    if rust is not None and min(f.shape) >= 2:
        return rust(np.ascontiguousarray(f, dtype=np.float64),
                    float(alpha1), float(alpha0), int(iterations))
    tau = sigma = 1.0 / np.sqrt(12.0)  # ‖L‖² ≤ 12
    u = f.copy()
    wx = xp.zeros_like(f)
    wy = xp.zeros_like(f)
    px = xp.zeros_like(f)
    py = xp.zeros_like(f)
    qxx = xp.zeros_like(f)
    qyy = xp.zeros_like(f)
    qxy = xp.zeros_like(f)
    ub = u.copy()
    wxb = wx.copy()
    wyb = wy.copy()
    for _ in range(iterations):
        # --- dual: p (on ∇ū - w̄), projected into the ball of radius α1 ---
        px += sigma * (_grad_x(ub) - wxb)
        py += sigma * (_grad_y(ub) - wyb)
        norm = xp.maximum(1.0, xp.sqrt(px * px + py * py) / alpha1)
        px /= norm
        py /= norm
        # --- dual: q (on E(w̄)), projected into the ball of radius α0 ---
        qxx += sigma * _grad_x(wxb)
        qyy += sigma * _grad_y(wyb)
        qxy += sigma * 0.5 * (_grad_y(wxb) + _grad_x(wyb))
        nq = xp.maximum(1.0, xp.sqrt(qxx * qxx + qyy * qyy + 2.0 * qxy * qxy) / alpha0)
        qxx /= nq
        qyy /= nq
        qxy /= nq
        # --- primal ---
        u_old = u
        wx_old = wx
        wy_old = wy
        div_p = _div_x(px) + _div_y(py)
        u = (u + tau * div_p + tau * f) / (1.0 + tau)  # prox of the data-fidelity term
        sym_x = _div_x(qxx) + 0.5 * _div_y(qxy)  # (E^T q)_x  (div = -adjoint of ∇)
        sym_y = _div_y(qyy) + 0.5 * _div_x(qxy)
        wx = wx + tau * (px + sym_x)
        wy = wy + tau * (py + sym_y)
        # --- extrapolation ---
        ub = 2.0 * u - u_old
        wxb = 2.0 * wx - wx_old
        wyb = 2.0 * wy - wy_old
    return u


@register
class TGVDenoise(Process):
    """TGV² denoising (Total Generalized Variation, 2nd order) — primal-dual, no dependency.

    True Bredies-Kunisch-Pock TGV (not a TV approximation): removes noise while preserving
    edges **and** smooth gradients (avoids the staircasing effect of TV).
    ``strength`` = regularization weight α1 (α0 = 2·α1). Pure numpy (the GIL can be released).
    """

    process_id = "TGVDenoise"
    category = "NoiseReduction"
    parameters = [
        Parameter("strength", "real", 0.1, 1e-3, 5.0, label=N_("Strength (α1)")),
        Parameter("iterations", "int", 100, 1, 2000, label=N_("Iterations")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from ..backend.xp import free_gpu_memory, is_oom, to_device, to_numpy

        a1 = max(float(self.strength), 1e-3)
        a0 = 2.0 * a1
        n = int(self.iterations)
        out = np.empty_like(data, dtype=np.float64)
        channels = data.shape[2]
        for c in range(channels):
            self._progress(c / channels, _t("TGV denoise — channel {n}/{total}").format(
                n=c + 1, total=channels))
            # Channel by channel, as before: converting the whole image to float64 in one go
            # would triple the peak memory, on GPU as on the host.
            plan = data[:, :, c].astype(np.float64)
            uploaded = to_device(plan)
            try:
                result = _tgv_denoise_channel(uploaded, a1, a0, n)
            except Exception as exc:
                if not is_oom(exc):
                    raise
                free_gpu_memory()
                result = _tgv_denoise_channel(plan, a1, a0, n)
            out[:, :, c] = to_numpy(result)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class ACDNR(Process):
    """Adaptive Contrast-Driven Noise Reduction: smooths the background, protects structures.

    A Gaussian blur is blended with the original through a protection mask derived from the
    local gradient (high-contrast areas — stars, edges — are preserved). The core of ACDNR,
    in numpy/scipy.
    """

    process_id = "ACDNR"
    category = "NoiseReduction"
    parameters = [
        Parameter("sigma", "real", 2.0, 0.1, 20.0, label=N_("Smoothing radius")),
        Parameter("protection", "real", 0.5, 0.0, 1.0, label=N_("Structure protection")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from scipy.ndimage import gaussian_filter, gaussian_gradient_magnitude

        out = np.empty_like(data)
        channels = data.shape[2]
        for c in range(channels):
            self._progress(c / channels, _t("ACDNR — channel {n}/{total}").format(
                n=c + 1, total=channels))
            ch = data[:, :, c]
            blurred = gaussian_filter(ch, sigma=float(self.sigma))
            grad = gaussian_gradient_magnitude(ch, sigma=1.0)
            g = grad / (float(grad.max()) or 1e-6)
            protect = np.clip(g * self.protection, 0.0, 1.0)  # 1 = keep the original
            out[:, :, c] = ch * protect + blurred * (1.0 - protect)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class NonLocalMeansDenoise(Process):
    """Non-Local Means denoising (skimage) — preserves faint stars and texture.

    Averages pixels with a similar neighborhood ("patch"), wherever they are within a search
    window. ``h`` (strength) is scaled by the noise estimated per channel. Slower than TV but
    respects point-like structures better.
    """

    process_id = "NonLocalMeansDenoise"
    category = "NoiseReduction"
    parameters = [
        Parameter("h", "real", 1.0, 0.1, 10.0, label=N_("Strength (× noise σ)")),
        Parameter("patch_size", "int", 5, 3, 15, label=N_("Patch size")),
        Parameter("patch_distance", "int", 6, 1, 30, label=N_("Search distance")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.restoration import denoise_nl_means, estimate_sigma

        out = np.empty_like(data)
        channels = data.shape[2]
        for c in range(channels):
            self._progress(c / channels, _t("NLM — channel {n}/{total}").format(
                n=c + 1, total=channels))
            ch = np.clip(data[:, :, c], 0.0, 1.0)
            sigma = float(estimate_sigma(ch))
            out[:, :, c] = denoise_nl_means(
                ch, h=self.h * sigma, sigma=sigma, fast_mode=True,
                patch_size=int(self.patch_size), patch_distance=int(self.patch_distance),
            )
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class FastNLMeansDenoise(Process):
    """**Fast** Non-Local Means (OpenCV) — for wide fields.

    ``cv2.fastNlMeansDenoising`` works in 8 bits: the image is quantized [0,1]→[0,255],
    denoised, then converted back. ``strength`` = OpenCV's h parameter (filtering strength).
    """

    process_id = "FastNLMeansDenoise"
    category = "NoiseReduction"
    parameters = [
        Parameter("strength", "real", 3.0, 0.1, 50.0, label=N_("Strength (h)")),
        Parameter("template_size", "int", 7, 3, 21, label=N_("Template size")),
        Parameter("search_size", "int", 21, 5, 51, label=N_("Search window")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import cv2

        tw = int(self.template_size) | 1  # OpenCV requires odd sizes
        sw = int(self.search_size) | 1
        out = np.empty_like(data)
        channels = data.shape[2]
        for c in range(channels):
            self._progress(c / channels, _t("Fast NLM — channel {n}/{total}").format(
                n=c + 1, total=channels))
            u8 = np.clip(data[:, :, c] * 255.0, 0, 255).astype(np.uint8)
            den = cv2.fastNlMeansDenoising(u8, None, float(self.strength), tw, sw)
            out[:, :, c] = den.astype(np.float32) / 255.0
        return out.astype(np.float32)
