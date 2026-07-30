"""The process runs headless (no shell) — the console-completeness pillar."""

from __future__ import annotations

import numpy as np
from retina import GaussianConvolution, Image, View


def test_gaussian_preserves_shape(synthetic_image):
    out = GaussianConvolution(sigma=2.0).execute_on_image(synthetic_image)
    assert out.data.shape == synthetic_image.data.shape
    assert out.data.dtype == np.float32


def test_gaussian_smooths_point(synthetic_image):
    """The convolution spreads the point-like star: the peak drops, its neighbours rise."""
    h, w = synthetic_image.height, synthetic_image.width
    peak_before = synthetic_image.sample(w // 2, h // 2)
    out = GaussianConvolution(sigma=2.0).execute_on_image(synthetic_image)
    peak_after = out.sample(w // 2, h // 2)
    neighbour_after = out.sample(w // 2 + 1, h // 2)
    neighbour_before = synthetic_image.sample(w // 2 + 1, h // 2)
    assert peak_after < peak_before
    assert neighbour_after > neighbour_before


def test_sigma_zero_is_identity(synthetic_image):
    out = GaussianConvolution(sigma=0.0).execute_on_image(synthetic_image)
    np.testing.assert_allclose(out.data, synthetic_image.data, atol=1e-6)


def test_execute_on_view_pushes_history():
    view = View(Image(np.zeros((16, 16, 1), dtype=np.float32) + 0.5), view_id="test")
    assert view.history_index == 0
    GaussianConvolution(sigma=1.5).execute_on(view)
    assert view.history_index == 1
    assert view.can_go_backward
    view.undo()
    assert view.history_index == 0
    assert not view.can_go_backward


def test_to_python_source_roundtrip():
    src = GaussianConvolution(sigma=3.5).to_python_source("view")
    assert src == "GaussianConvolution(sigma=3.5).execute_on(view)"
