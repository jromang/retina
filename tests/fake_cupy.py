"""A cheap knock-off CuPy, to exercise the GPU branches on a machine that has none.

It computes nothing that numpy does not: its only job is to **pass for cupy** in the eyes of
the dispatch (`xp._is_cupy` tests the module name) and to provide the few symbols the code
touches — `asarray`, `.get()`, the memory pool, the FFT module, the out-of-memory error.

It does not replace the parity tests against the **real** CuPy (`test_gpu_parity.py`, under
`importorskip`): it checks the wiring, not the numerical correctness. That is the usual
division of labour — CI exercises the paths, the equipped machine checks the results.
"""

from __future__ import annotations

import sys
import types

import numpy as np


class ndarray(np.ndarray):
    """A numpy ndarray that *claims* to come from cupy."""

    __module__ = "cupy"

    def get(self):
        return np.asarray(self).view(np.ndarray)


def _wrap(value):
    """Return a numpy array dressed up as our fake cupy."""
    if isinstance(value, np.ndarray) and not isinstance(value, ndarray):
        return value.view(ndarray)
    if isinstance(value, tuple):
        return tuple(_wrap(v) for v in value)
    return value


class _Delegating(types.ModuleType):
    """Module that delegates to a numpy/scipy module, re-wrapping whatever comes out."""

    def __init__(self, name, target):
        super().__init__(name)
        self._target = target

    def __getattr__(self, name):
        attribute = getattr(self._target, name)
        if not callable(attribute):
            return attribute

        def wrapper(*args, **kwargs):
            return _wrap(attribute(*args, **kwargs))

        return wrapper


class OutOfMemoryError(MemoryError):
    """Namesake of `cupy.cuda.memory.OutOfMemoryError` — recognised by its name."""

    __module__ = "cupy.cuda.memory"


class _Pool:
    def __init__(self):
        self.frees = 0

    def free_all_blocks(self):
        self.frees += 1


POOL = _Pool()


def install(monkeypatch, *, available: bool = True):
    """Inject the fake cupy into ``sys.modules`` and reset the availability cache.

    Returns the root module, on which tests set whatever they need (for instance an
    ``asarray`` that raises, to exercise the fallback).
    """
    from retina.backend import xp

    cupy = _Delegating("cupy", np)
    cupy.ndarray = ndarray
    cupy.asarray = lambda a, *a_, **k: _wrap(np.asarray(a, *a_, **k))
    cupy.get_default_memory_pool = lambda: POOL

    runtime = types.ModuleType("cupy.cuda.runtime")
    runtime.getDeviceCount = lambda: 1 if available else 0

    class _Device:
        def __init__(self, *a):
            pass

        def synchronize(self):
            pass

    cuda = types.ModuleType("cupy.cuda")
    cuda.runtime = runtime
    cuda.Device = _Device
    memory = types.ModuleType("cupy.cuda.memory")
    memory.OutOfMemoryError = OutOfMemoryError
    cuda.memory = memory
    cupy.cuda = cuda

    from scipy import fft as scipy_fft
    from scipy import ndimage as scipy_ndimage

    cupyx = types.ModuleType("cupyx")
    cupyx_scipy = types.ModuleType("cupyx.scipy")
    cupyx_scipy.fft = _Delegating("cupyx.scipy.fft", scipy_fft)
    cupyx_scipy.ndimage = _Delegating("cupyx.scipy.ndimage", scipy_ndimage)
    cupyx.scipy = cupyx_scipy

    for name, module in (("cupy", cupy), ("cupy.cuda", cuda), ("cupy.cuda.runtime", runtime),
                        ("cupy.cuda.memory", memory), ("cupyx", cupyx),
                        ("cupyx.scipy", cupyx_scipy),
                        ("cupyx.scipy.fft", cupyx_scipy.fft),
                        ("cupyx.scipy.ndimage", cupyx_scipy.ndimage)):
        monkeypatch.setitem(sys.modules, name, module)

    # The `gpu_available` cache is global: without a reset, the first test that installs the
    # fake cupy would freeze the answer for the whole session. Resetting it *after* the test
    # is the calling fixture's job (cf. `test_gpu_dispatch.py`).
    xp.reset_availability()
    return cupy
