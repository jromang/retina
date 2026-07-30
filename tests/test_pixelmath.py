"""PixelMath (Python/asteval engine): numpy expressions, multi-image, options."""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image, PixelMath


@pytest.fixture
def ramp():
    return Image(np.linspace(0.0, 1.0, 40, dtype=np.float32).reshape(5, 8, 1))


# --- basic expressions ---------------------------------------------------------
def test_scale(ramp):
    out = PixelMath(expression="img * 0.5").execute_on_image(ramp)
    np.testing.assert_allclose(out.data, ramp.data * 0.5, atol=1e-6)


def test_power_and_sqrt(ramp):
    out = PixelMath(expression="img ** 2", truncate=False).execute_on_image(ramp)
    np.testing.assert_allclose(out.data, ramp.data**2, atol=1e-6)
    out2 = PixelMath(expression="sqrt(img)").execute_on_image(ramp)
    np.testing.assert_allclose(out2.data, np.sqrt(ramp.data), atol=1e-5)


def test_global_stat_broadcasts(ramp):
    med = float(np.median(ramp.data))
    out = PixelMath(expression="median(img)", truncate=False).execute_on_image(ramp)
    assert out.data.shape == ramp.data.shape
    assert np.allclose(out.data, med, atol=1e-6)


def test_symbols_multiline(ramp):
    out = PixelMath(symbols="a = median(img)", expression="img - a + 0.5").execute_on_image(ramp)
    expected = np.clip(ramp.data - np.median(ramp.data) + 0.5, 0, 1)
    np.testing.assert_allclose(out.data, expected, atol=1e-6)


def test_where_threshold(ramp):
    out = PixelMath(expression="where(img > 0.5, 1.0, 0.0)").execute_on_image(ramp)
    assert set(np.unique(out.data)) <= {0.0, 1.0}
    # iif is an alias of where
    out2 = PixelMath(expression="iif(img > 0.5, 1.0, 0.0)").execute_on_image(ramp)
    np.testing.assert_allclose(out.data, out2.data)


def test_coordinate_gradient():
    img = Image(np.zeros((4, 10, 1), dtype=np.float32))
    out = PixelMath(expression="x").execute_on_image(img)
    row = out.data[0, :, 0]
    assert row[0] == pytest.approx(0.0) and row[-1] == pytest.approx(1.0)
    assert np.all(np.diff(row) > 0)


def test_spatial_gaussian_smooths(ramp):
    noise = np.random.default_rng(0).normal(0, 0.05, ramp.data.shape)
    noisy = Image(np.clip(ramp.data + noise, 0, 1).astype(np.float32))
    out = PixelMath(expression="gaussian(img, 2)", truncate=False).execute_on_image(noisy)
    assert out.data.std() < noisy.data.std()  # blurring reduces the variance


def test_median_filter_runs(ramp):
    out = PixelMath(expression="median_filter(img, 3)").execute_on_image(ramp)
    assert out.data.shape == ramp.data.shape


def test_fft_roundtrip(ramp):
    out = PixelMath(expression="real(ifft2(fft2(img)))", truncate=False).execute_on_image(ramp)
    np.testing.assert_allclose(out.data, ramp.data, atol=1e-4)


def test_robust_stat_and_percentile(ramp):
    out = PixelMath(expression="percentile(img, 50)", truncate=False).execute_on_image(ramp)
    assert np.allclose(out.data, np.percentile(ramp.data, 50), atol=1e-5)
    out2 = PixelMath(expression="mad_std(img)", truncate=False).execute_on_image(ramp)
    from astropy.stats import mad_std
    assert np.allclose(out2.data, float(mad_std(ramp.data)), atol=1e-5)


def test_invalid_expression_raises(ramp):
    with pytest.raises(ValueError):
        PixelMath(expression="img + )(").execute_on_image(ramp)
    with pytest.raises(ValueError):
        PixelMath(expression="img + unknown").execute_on_image(ramp)


# --- colour / channels (numpy broadcasting) -----------------------------------
def _color():
    return Image(np.dstack([
        np.full((2, 2), 0.2, np.float32),
        np.full((2, 2), 0.6, np.float32),
        np.full((2, 2), 0.9, np.float32),
    ]))


def test_per_channel_gain_via_broadcast():
    out = PixelMath(expression="img * array([1.5, 1.0, 0.5])").execute_on_image(_color())
    assert np.allclose(out.data[:, :, 0], 0.3)
    assert np.allclose(out.data[:, :, 1], 0.6)
    assert np.allclose(out.data[:, :, 2], 0.45)


def test_channel_extraction():
    out = PixelMath(expression="img[:, :, 0:1]").execute_on_image(_color())
    assert np.allclose(out.data, 0.2)  # every channel ← red channel (0.2)


def test_per_channel_stat():
    bg = PixelMath(
        expression="median(img, axis=(0, 1), keepdims=True) + img*0", truncate=False
    ).execute_on_image(_color())
    assert np.allclose(bg.data[:, :, 0], 0.2)
    assert np.allclose(bg.data[:, :, 1], 0.6)
    assert np.allclose(bg.data[:, :, 2], 0.9)


# --- multi-images --------------------------------------------------------------
def test_multi_image_via_set_images():
    a = Image(np.full((3, 3, 1), 0.3, dtype=np.float32))
    b = Image(np.full((3, 3, 1), 0.4, dtype=np.float32))
    out = PixelMath(expression="(a + b) / 2").set_images({"a": a, "b": b}).execute_on_image(a)
    np.testing.assert_allclose(out.data, np.full((3, 3, 1), 0.35), atol=1e-6)


def test_multi_image_via_app_provider():
    app = Application()
    a = Image(np.full((3, 3, 1), 0.2, dtype=np.float32))
    b = Image(np.full((3, 3, 1), 0.5, dtype=np.float32))
    app.new_window(a, window_id="A")
    win_b = app.new_window(b, window_id="B")
    app.set_active_window(win_b)
    app.apply(PixelMath(expression="A + img"))  # A + B on the active view (B)
    np.testing.assert_allclose(win_b.main_view.image.data, np.full((3, 3, 1), 0.7), atol=1e-6)


# --- output: rescale / truncate / new image ------------------------------------
def test_rescale_output():
    img = Image(np.linspace(-1.0, 3.0, 16, dtype=np.float32).reshape(4, 4, 1))
    out = PixelMath(expression="img", rescale=True, truncate=False).execute_on_image(img)
    assert out.data.min() == pytest.approx(0.0)
    assert out.data.max() == pytest.approx(1.0)


def test_truncate_default(ramp):
    out = PixelMath(expression="img * 5").execute_on_image(ramp)
    assert out.data.max() <= 1.0 + 1e-6


def test_create_new_image_makes_window():
    app = Application()
    src = Image(np.full((3, 3, 1), 0.5, dtype=np.float32))
    app.new_window(src, window_id="src")
    before = len(app.windows)
    app.apply(PixelMath(expression="img * 0", create_new_image=True, new_image_id="black"))
    assert len(app.windows) == before + 1
    assert np.allclose(app.windows[-1].main_view.image.data, 0.0)
    assert np.allclose(app.windows[0].main_view.image.data, 0.5)  # source untouched
