"""Array module selection — the numpy/CuPy "xp" announced by ARCHITECTURE.md.

Two responsibilities that must be kept distinct, on pain of the bug described below:

- **Dispatch follows the type.** ``get_array_module``, ``ndimage_for``, ``fft_for`` and
  ``to_numpy`` look at *what they are given* and nothing else. A CuPy array routes to cupy,
  full stop — even with the GPU switched off, otherwise there would be no way to bring it
  back down.
- **Policy is decided at mount time.** ``to_device`` is the **only** place that consults the
  kill switch, the preference, CuPy's availability and the size of the data. That is where
  going to the GPU is chosen, and nowhere else.

The bug this separation avoids: ``is_gpu`` mixed the two (type **and** policy), so that with
a genuine CuPy array and ``RETINA_GPU=0`` it returned ``False`` — hence ``get_array_module``
returned numpy, and ``np.pad(cupy_array)`` raised. ``to_numpy`` broke the same way, which made
the kill switch unusable at the very moment it was needed.

``is_gpu`` stays public and keeps its *policy* meaning ("should this array be processed on
the GPU?"); the guarantor of the kill switch is ``to_device``, which short-circuits **before**
any import of cupy.
"""

from __future__ import annotations

import os

import numpy as np

#: Below this, going to the GPU costs more than it returns: the PCIe round trip and the
#: kernel launches dominate the computation. The threshold mainly protects the **real-time
#: preview**, which loops over small previews.
#:
#: **Measured, not guessed** (RTX 5080, `profile_hotspots.py --gpu --seuil`): total variation
#: is the more sensitive candidate, because one iteration costs little there — it loses at
#: 0.01 Mpx (×0.2), catches up around 0.05 Mpx (×0.8) and pulls ahead at 0.1 Mpx (×1.4).
#: Richardson-Lucy, for its part, wins from 0.02 Mpx (×1.8) because one iteration costs two
#: FFTs there. 100,000 pixels is therefore the point at which the less favorable of the two
#: stops losing.
GPU_MIN_PIXELS = 100_000

_available: bool | None = None  # cache of ``gpu_available`` (importing cupy costs ~1 s)


def gpu_disabled() -> bool:
    """GPU switched off? The environment variable wins, then the preference.

    The order is not indifferent: ``RETINA_GPU=0`` serves debugging and fair benchmarks, and
    must therefore be able to override a user setting.
    """
    if os.environ.get("RETINA_GPU", "").strip() == "0":
        return True
    try:
        from .. import preferences

        return not preferences.value("performance.gpu_enabled")
    except Exception:  # minimal domain, unreadable preferences: we block nothing
        return False


def _is_cupy(arr) -> bool:
    """True if ``arr`` is a CuPy array — **a question of type alone**, no policy.

    The test is on the module name rather than on ``isinstance``: being able to answer must
    not cost an import of cupy on a machine that does not have it.
    """
    return type(arr).__module__.split(".")[0] == "cupy"


def gpu_available() -> bool:
    """Is CuPy installed, with a usable GPU? The result is cached.

    Never raises: no CuPy, no driver, no card — each of them a "no".
    """
    global _available
    if _available is None:
        try:
            import cupy  # type: ignore

            _available = cupy.cuda.runtime.getDeviceCount() > 0
        except Exception:
            _available = False
    return _available


def reset_availability() -> None:
    """Forget the result of :func:`gpu_available` — for the tests, which simulate CuPy."""
    global _available
    _available = None


def to_device(arr, *, min_pixels: int | None = None):
    """Move ``arr`` to the GPU if it is worth it; otherwise return it unchanged.

    **The repository's only mount point.** Never raises: no GPU, memory full, angry driver —
    in every case the input is returned as is and the computation happens on the CPU, which is
    slow but correct.

    ``min_pixels`` defaults to ``GPU_MIN_PIXELS``, **read at call time** rather than frozen as
    a default value: a constant captured at definition time can neither be adjusted for a
    benchmark, nor overridden by a test, nor one day wired to a preference.
    """
    if _is_cupy(arr):
        return arr
    if gpu_disabled() or not gpu_available():
        return arr
    threshold = GPU_MIN_PIXELS if min_pixels is None else min_pixels
    if int(getattr(arr, "size", 0)) < int(threshold):
        return arr
    try:
        import cupy  # type: ignore

        return cupy.asarray(arr)
    except Exception:  # not enough memory even to mount, context lost…
        return arr


def is_oom(exc: BaseException) -> bool:
    """Is the exception a GPU out-of-memory error?

    Recognized **by its name**, never by ``isinstance``: the ``except`` clause on a machine
    without CUDA must not trigger an import of cupy just to learn there is nothing to
    recognize.
    """
    classe = type(exc)
    return (classe.__module__.split(".")[0] == "cupy"
            and "OutOfMemory" in classe.__name__)


def free_gpu_memory() -> None:
    """Return to the driver the blocks CuPy's pool holds — before a fallback after an OOM."""
    try:
        import cupy  # type: ignore

        cupy.get_default_memory_pool().free_all_blocks()
    except Exception:
        pass


def synchronize() -> None:
    """Wait for the GPU work in flight to finish (a no-op without a GPU).

    Indispensable in order to **measure**: CuPy launches are asynchronous, and an
    unsynchronized ``perf_counter`` times the dispatch of the orders, not the computation.
    """
    if not gpu_available():
        return
    try:
        import cupy  # type: ignore

        cupy.cuda.Device().synchronize()
    except Exception:
        pass


def is_gpu(arr) -> bool:
    """Should this array be processed on the GPU? (type **and** policy)

    Distinct from :func:`_is_cupy`, which looks only at the type: it is that distinction which
    lets ``to_numpy`` bring a CuPy array back down even under ``RETINA_GPU=0``.
    """
    return _is_cupy(arr) and not gpu_disabled()


def get_array_module(*arrays):
    """The "xp" module of the given arrays: cupy if one of them lives on the GPU, else numpy."""
    if any(_is_cupy(a) for a in arrays):
        import cupy  # type: ignore

        return cupy
    return np


def ndimage_for(*arrays):
    """The matching ``ndimage``: ``cupyx.scipy.ndimage`` on GPU, ``scipy.ndimage`` otherwise."""
    if any(_is_cupy(a) for a in arrays):
        from cupyx.scipy import ndimage  # type: ignore

        return ndimage
    from scipy import ndimage

    return ndimage


def fft_for(*arrays):
    """The matching FFT module: ``cupyx.scipy.fft`` on GPU, ``scipy.fft`` otherwise.

    ``cupyx.scipy.fft`` caches its cuFFT plans by shape, which is exactly what a deconvolution
    loop needs: all its transforms share the same size, so the plan is built once. On the CPU
    side, ``scipy.fft`` is also slightly faster than ``numpy.fft``, and knows
    ``next_fast_len``.
    """
    if any(_is_cupy(a) for a in arrays):
        from cupyx.scipy import fft  # type: ignore

        return fft
    from scipy import fft

    return fft


def to_numpy(arr) -> np.ndarray:
    """Bring an array back to the host (a no-op for an ndarray)."""
    if _is_cupy(arr):
        return arr.get()
    return np.asarray(arr)
