"""Multiscale (starlet) + local histogram equalisation (CLAHE)."""

from __future__ import annotations

import numpy as np
from retina import Image, get


def test_starlet_reconstruction_is_identity():
    """Neutral biases + no threshold → faithful reconstruction (a starlet property)."""
    rng = np.random.default_rng(0)
    img = Image((rng.random((48, 48, 1)) * 0.8 + 0.1).astype(np.float32))
    out = get("MultiscaleLinearTransform")(scales=5).execute_on_image(img)
    np.testing.assert_allclose(out.data, img.data, atol=1e-5)


def test_starlet_noise_threshold_denoises():
    rng = np.random.default_rng(1)
    clean = np.full((64, 64, 1), 0.5, dtype=np.float32)
    noisy = np.clip(clean + rng.normal(0, 0.05, clean.shape), 0, 1).astype(np.float32)
    out = get("MultiscaleLinearTransform")(
        scales=4, noise_threshold=3.0
    ).execute_on_image(Image(noisy))
    assert out.data.std() < noisy.std()


def test_starlet_bias_changes_structure():
    rng = np.random.default_rng(2)
    img = Image((rng.random((48, 48, 1)) * 0.5 + 0.25).astype(np.float32))
    # damp the two finest scales (aggressive denoising) → reduced variance
    out = get("MultiscaleLinearTransform")(
        scales=5, bias=[0.0, 0.0, 1.0, 1.0, 1.0]
    ).execute_on_image(img)
    assert out.data.std() < img.data.std()


def test_clahe_runs_and_stays_in_range():
    ramp = Image(np.linspace(0.1, 0.6, 64 * 64, dtype=np.float32).reshape(64, 64, 1))
    out = get("LocalHistogramEqualization")(clip_limit=0.02).execute_on_image(ramp)
    assert out.data.shape == ramp.data.shape
    assert out.data.min() >= 0.0 and out.data.max() <= 1.0
    assert out.data.std() != ramp.data.std()  # the local contrast has changed
