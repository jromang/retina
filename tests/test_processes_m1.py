"""M1 processes: HistogramTransformation, CurvesTransformation, PixelMath (headless)."""

from __future__ import annotations

import numpy as np
import pytest
from retina import CurvesTransformation, HistogramTransformation, Image


@pytest.fixture
def gray():
    return Image(np.linspace(0.0, 1.0, 64, dtype=np.float32).reshape(8, 8, 1))


# --- HistogramTransformation ---------------------------------------------------
def test_histogram_identity(gray):
    out = HistogramTransformation(shadows=0.0, midtones=0.5, highlights=1.0).execute_on_image(gray)
    np.testing.assert_allclose(out.data, gray.data, atol=1e-6)


def test_histogram_midtones_brightens(gray):
    out = HistogramTransformation(midtones=0.25).execute_on_image(gray)
    # midtones < 0.5 lifts the mid-tones: output ≥ input, brighter on average
    assert out.mean() > gray.mean()
    assert np.all(out.data >= gray.data - 1e-6)


# --- CurvesTransformation ------------------------------------------------------
def test_curves_identity(gray):
    out = CurvesTransformation(points=[[0.0, 0.0], [1.0, 1.0]]).execute_on_image(gray)
    np.testing.assert_allclose(out.data, gray.data, atol=1e-6)


def test_curves_lift_is_monotone_and_brighter(gray):
    out = CurvesTransformation(points=[[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]).execute_on_image(gray)
    assert out.mean() > gray.mean()
    flat = out.data.ravel()
    assert np.all(np.diff(flat) >= -1e-6)  # monotonically increasing (no overshoot)


# PixelMath has its own full suite: see tests/test_pixelmath.py
