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


def test_histogram_per_channel_triples(gray):
    """An auto-stretch is computed per channel; a single triple would shift the colours."""
    rgb = Image(np.tile(gray.data, (1, 1, 3)))
    process = HistogramTransformation(channels=[0.0, 0.5, 1.0, 0.0, 0.25, 1.0, 0.0, 0.75, 1.0])
    out = process.execute_on_image(rgb)

    np.testing.assert_allclose(out.data[..., 0], rgb.data[..., 0], atol=1e-6)  # identity
    assert out.data[..., 1].mean() > rgb.data[..., 1].mean()  # midtones 0.25 brightens
    assert out.data[..., 2].mean() < rgb.data[..., 2].mean()  # midtones 0.75 darkens


def test_histogram_channels_default_is_the_old_behaviour(gray):
    """Recipes written before the parameter existed must read back unchanged."""
    scalars = HistogramTransformation(midtones=0.3).execute_on_image(gray)
    explicit = HistogramTransformation(channels=[0.0, 0.3, 1.0]).execute_on_image(gray)
    np.testing.assert_allclose(scalars.data, explicit.data, atol=1e-7)


def test_histogram_channels_must_come_in_triples(gray):
    with pytest.raises(ValueError, match="triples"):
        HistogramTransformation(channels=[0.0, 0.5]).execute_on_image(gray)


def test_from_stf_reproduces_the_display_on_the_pixels():
    """The point of the "apply the screen stretch" gesture: same numbers, in the pixels."""
    from retina.model.stf import STF, ChannelSTF

    rng = np.random.default_rng(3)
    image = Image((rng.random((6, 6, 3)) * 0.01).astype(np.float32))
    stf = STF(channels=[
        ChannelSTF(shadows=0.001, midtones=0.02, highlights=0.9),
        ChannelSTF(shadows=0.002, midtones=0.03, highlights=0.95),
        ChannelSTF(shadows=0.000, midtones=0.04, highlights=1.0),
    ])

    baked = HistogramTransformation.from_stf(stf).execute_on_image(image)
    np.testing.assert_allclose(baked.data, stf.apply(image), atol=1e-6)


def test_from_stf_collapses_equal_channels_to_the_scalars():
    """The common case must stay readable in the echo, not a nine-number list."""
    from retina.model.stf import STF, ChannelSTF

    same = ChannelSTF(shadows=0.1, midtones=0.3, highlights=0.9)
    process = HistogramTransformation.from_stf(STF(channels=[same, same, same]))

    assert process.channels == []
    assert (process.shadows, process.midtones, process.highlights) == (0.1, 0.3, 0.9)


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
