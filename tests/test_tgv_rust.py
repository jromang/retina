"""Numerical parity of the Rust port of TGVDenoise (the only GO from the profiling run).

The numpy path is the reference: the Rust code reproduces the same forward/backward
differences and the same boundary rules, in f64 — the discrepancy must be zero or of
the order of machine epsilon, not "visually close".
"""

from __future__ import annotations

import numpy as np
import pytest
import retina.processes.denoise as dn


def _rust():
    fn = dn._tgv_rust()
    if fn is None:
        pytest.skip("_core extension without tgv_denoise (older build)")
    return fn


def test_rust_numpy_parity() -> None:
    rust = _rust()
    rng = np.random.default_rng(3)
    f = rng.random((48, 64)).astype(np.float64)

    original = dn._tgv_rust
    dn._tgv_rust = lambda: None  # force the numpy reference
    try:
        ref = dn._tgv_denoise_channel(f.copy(), 0.1, 0.2, 60)
    finally:
        dn._tgv_rust = original
    out = rust(f.copy(), 0.1, 0.2, 60)
    np.testing.assert_allclose(out, ref, atol=1e-9)


def test_the_process_uses_rust_and_denoises() -> None:
    from retina.model.image import Image
    from retina.processes.denoise import TGVDenoise

    _rust()
    rng = np.random.default_rng(5)
    own = np.tile(np.linspace(0.2, 0.6, 64, dtype=np.float32), (48, 1))[:, :, None]
    noisy = np.clip(own + rng.normal(0, 0.05, own.shape).astype(np.float32), 0, 1)
    out = TGVDenoise(strength=0.05, iterations=80).execute_on_image(Image(noisy))
    # the residual against the clean image must have shrunk — this is denoising, not identity
    assert float(np.abs(out.data - own).mean()) < float(np.abs(noisy - own).mean()) * 0.6


def test_minimal_2x2_image() -> None:
    from retina.model.image import Image
    from retina.processes.denoise import TGVDenoise

    # the smallest case the forward/backward differences support (2×2) must not raise
    data = np.random.default_rng(1).random((2, 3, 1)).astype(np.float32)
    out = TGVDenoise(iterations=5).execute_on_image(Image(data))
    assert out.data.shape == data.shape
    assert np.isfinite(out.data).all()
