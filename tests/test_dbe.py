"""DynamicBackgroundExtraction: fits and removes a background from sample points."""

from __future__ import annotations

import numpy as np
import pytest
from retina import Image, get


def _gradient(h=100, w=100):
    yy, xx = np.mgrid[0:h, 0:w]
    return (0.1 + 0.35 * xx / w + 0.25 * yy / h).astype(np.float32)[:, :, None]


def _grid_samples():
    return [(x, y) for x in (10, 50, 90) for y in (10, 50, 90)]


def test_dbe_rbf_removes_gradient():
    grad = _gradient()
    out = get("DynamicBackgroundExtraction")(
        samples=_grid_samples(), model="rbf", sample_radius=5, subtract=True, pedestal=0.1
    ).execute_on_image(Image(grad))
    assert out.data.std() < grad.std() * 0.2  # gradient strongly flattened


def test_dbe_poly_removes_gradient():
    grad = _gradient()
    out = get("DynamicBackgroundExtraction")(
        samples=_grid_samples(), model="poly", degree=1, sample_radius=5, pedestal=0.1
    ).execute_on_image(Image(grad))
    assert out.data.std() < grad.std() * 0.2  # a plane is enough for a linear gradient


def test_dbe_rejects_stars_in_samples():
    """A sample placed on a star: the robust median ignores the stellar peak."""
    grad = _gradient()
    data = grad.copy()
    data[50, 50, 0] = 1.0  # a star right on top of a sample point
    out = get("DynamicBackgroundExtraction")(
        samples=_grid_samples(), model="rbf", sample_radius=8, tolerance=3.0, pedestal=0.1
    ).execute_on_image(Image(data))
    # the model stays smooth: no aberrant "dip" around (50,50)
    assert out.data.std() < grad.std() * 0.3


def test_dbe_output_model():
    grad = _gradient()
    model = get("DynamicBackgroundExtraction")(
        samples=_grid_samples(), model="rbf", subtract=False
    ).execute_on_image(Image(grad))
    # the model approximates the gradient (strong correlation)
    corr = np.corrcoef(model.data.ravel(), grad.ravel())[0, 1]
    assert corr > 0.98


def test_dbe_needs_samples():
    with pytest.raises(ValueError):
        get("DynamicBackgroundExtraction")(samples=[(1, 1)]).execute_on_image(Image(_gradient()))
