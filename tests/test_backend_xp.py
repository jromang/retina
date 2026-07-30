"""The backend package: import compatibility intact, xp dispatch on the input type."""

from __future__ import annotations

import numpy as np


def test_import_compat_unchanged() -> None:
    # The historical contract: these three names, in this place.
    from retina.backend import HAS_RUST, backend_name, gaussian_convolve

    assert isinstance(HAS_RUST, bool)
    assert backend_name() in ("rust", "numpy")
    out = gaussian_convolve(np.random.default_rng(0).random((8, 8, 1)).astype(np.float32), 1.5)
    assert out.shape == (8, 8, 1)


def test_xp_defaults_to_numpy() -> None:
    from retina.backend import get_array_module, is_gpu, ndimage_for, to_numpy

    arr = np.zeros((2, 2), dtype=np.float32)
    assert get_array_module(arr) is np
    assert is_gpu(arr) is False
    assert to_numpy(arr) is not None
    from scipy import ndimage

    assert ndimage_for(arr) is ndimage


def test_retina_gpu_0_forces_numpy(monkeypatch) -> None:
    """The kill-switch: even a real CuPy array would be treated as a host array."""
    from retina.backend import xp

    class FakeCupy:  # fakes type(arr).__module__ == "cupy...."
        pass

    FakeCupy.__module__ = "cupy"
    fake = FakeCupy()
    monkeypatch.delenv("RETINA_GPU", raising=False)
    assert xp.is_gpu(fake) is True
    monkeypatch.setenv("RETINA_GPU", "0")
    assert xp.is_gpu(fake) is False
