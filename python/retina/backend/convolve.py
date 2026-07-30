"""Gaussian convolution — the reference operator of the dispatch.

Reference path: the native Rust core ``retina._core`` (CPU, multicore, GIL released).
Fallbacks: scipy if present, otherwise a pure numpy implementation — so that the domain stays
testable even without a compiled extension. GPU: a CuPy input routes to
``cupyx.scipy.ndimage`` (see :mod:`retina.backend.xp`).
"""

from __future__ import annotations

import numpy as np

from .xp import is_gpu, ndimage_for

try:  # native Rust core
    from .. import _core as _rust_core  # type: ignore[attr-defined]

    HAS_RUST = True
except Exception:  # pragma: no cover - depends on the build
    _rust_core = None
    HAS_RUST = False


def gaussian_convolve(data: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian convolution of an ``(H, W, C)`` float32 array."""
    if is_gpu(data):  # GPU
        ndimage = ndimage_for(data)
        out = data.copy()
        for c in range(data.shape[2]):
            out[:, :, c] = ndimage.gaussian_filter(data[:, :, c], sigma=sigma)
        return out

    arr = np.ascontiguousarray(data, dtype=np.float32)
    if sigma <= 0.0:
        return arr.copy()

    if HAS_RUST:  # reference path
        return _rust_core.gaussian_convolve(arr, float(sigma))

    # --- CPU fallbacks (without the compiled extension) -----------------------
    try:
        from scipy.ndimage import gaussian_filter  # type: ignore

        out = np.empty_like(arr)
        for c in range(arr.shape[2]):
            out[:, :, c] = gaussian_filter(arr[:, :, c], sigma=sigma, mode="reflect")
        return out
    except Exception:
        return _numpy_gaussian(arr, sigma)


def _numpy_gaussian(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Pure numpy separable Gaussian convolution (reflected border)."""
    radius = max(1, int(np.ceil(3.0 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x**2) / (2.0 * sigma**2))
    k /= k.sum()

    def conv1d(a: np.ndarray, axis: int) -> np.ndarray:
        pad = [(0, 0)] * a.ndim
        pad[axis] = (radius, radius)
        ap = np.pad(a, pad, mode="reflect")
        out = np.zeros_like(a)
        for i, kv in enumerate(k):
            sl = [slice(None)] * a.ndim
            sl[axis] = slice(i, i + a.shape[axis])
            out += kv * ap[tuple(sl)]
        return out

    out = np.empty_like(arr)
    for c in range(arr.shape[2]):
        ch = conv1d(conv1d(arr[:, :, c], 0), 1)
        out[:, :, c] = ch
    return out.astype(np.float32)


def backend_name(data: np.ndarray | None = None) -> str:
    if data is not None and is_gpu(data):
        return "cupy"
    return "rust" if HAS_RUST else "numpy"
