"""ChannelMatch, alpha channels (creation, extraction, RGBA raster round trip), FindingChart.

Purely headless tests: `execute_on` against an Image, `execute_global` against a fresh
Application — not one interface pixel. FindingChart runs without network access
(catalog='none' or `set_objects`).
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.processes.alpha import CreateAlphaChannels, ExtractAlphaChannels
from retina.processes.channels import ChannelMatch


def _rgb_star(width: int = 48, height: int = 40) -> np.ndarray:
    """A gaussian star, identical on all three channels."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    star = np.exp(-(((x - 20.0) ** 2 + (y - 18.0) ** 2) / 8.0))
    return np.stack([star] * 3, axis=-1).astype(np.float32)


# --- ChannelMatch --------------------------------------------------------------
def test_channelmatch_realigns_a_shifted_channel() -> None:
    from scipy import ndimage

    data = _rgb_star()
    # R channel shifted by (+2.5, -1.5): the counter-move must bring it back onto G
    data[:, :, 0] = ndimage.shift(data[:, :, 0], (2.5, -1.5), order=3)
    out = ChannelMatch(dx=[1.5, 0.0, 0.0], dy=[-2.5, 0.0, 0.0]).execute_on_image(Image(data))
    r_pos = np.unravel_index(np.argmax(out.data[:, :, 0]), out.data.shape[:2])
    g_pos = np.unravel_index(np.argmax(out.data[:, :, 1]), out.data.shape[:2])
    assert abs(r_pos[0] - g_pos[0]) <= 1 and abs(r_pos[1] - g_pos[1]) <= 1


def test_channelmatch_linear_factors() -> None:
    data = np.full((8, 8, 3), 0.4, dtype=np.float32)
    out = ChannelMatch(factors=[0.5, 1.0, 2.0]).execute_on_image(Image(data))
    assert out.data[0, 0, 0] == pytest.approx(0.2)
    assert out.data[0, 0, 1] == pytest.approx(0.4)
    assert out.data[0, 0, 2] == pytest.approx(0.8)  # clamped to 1 only beyond that


def test_channelmatch_mono_is_a_noop() -> None:
    data = np.random.default_rng(1).random((6, 6, 1)).astype(np.float32)
    out = ChannelMatch(dx=[3.0], dy=[3.0]).execute_on_image(Image(data))
    assert np.array_equal(out.data, data)


# --- alpha -----------------------------------------------------------------------
def test_create_constant_alpha_then_extract() -> None:
    rgb = _rgb_star(16, 12)
    with_alpha = CreateAlphaChannels(mode="constant", value=0.25).execute_on_image(Image(rgb))
    assert with_alpha.channels == 4
    assert with_alpha.has_alpha and with_alpha.nominal_channels == 3
    assert with_alpha.alpha is not None and float(with_alpha.alpha[0, 0]) == pytest.approx(0.25)

    extracted = ExtractAlphaChannels(mode="extract").execute_on_image(with_alpha)
    assert extracted.channels == 1
    assert float(extracted.data[0, 0, 0]) == pytest.approx(0.25)

    without_alpha = ExtractAlphaChannels(mode="remove").execute_on_image(with_alpha)
    assert without_alpha.channels == 3 and not without_alpha.has_alpha
    assert np.allclose(without_alpha.data, rgb)


def test_create_alpha_luminance_and_grayscale() -> None:
    rgb = _rgb_star(10, 10)
    lum = CreateAlphaChannels(mode="luminance").execute_on_image(Image(rgb))
    expected = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    assert np.allclose(lum.alpha, expected, atol=1e-6)

    gray = Image(rgb[:, :, :1].copy())
    ga = CreateAlphaChannels(mode="constant", value=1.0).execute_on_image(gray)
    assert ga.channels == 2 and ga.nominal_channels == 1 and ga.has_alpha


def test_create_alpha_replaces_the_existing_one() -> None:
    rgb = _rgb_star(8, 8)
    once = CreateAlphaChannels(mode="constant", value=0.3).execute_on_image(Image(rgb))
    twice = CreateAlphaChannels(mode="constant", value=0.9).execute_on_image(once)
    assert twice.channels == 4  # replaced, not stacked
    assert float(twice.alpha[0, 0]) == pytest.approx(0.9)


def test_extract_without_alpha_raises() -> None:
    with pytest.raises(ValueError):
        ExtractAlphaChannels(mode="extract").execute_on_image(Image(_rgb_star(6, 6)))


def test_extract_through_the_app_opens_a_window() -> None:
    from retina.app import Application

    app = Application()
    rgba = CreateAlphaChannels(mode="constant", value=0.5).execute_on_image(Image(_rgb_star(8, 8)))
    app.new_window(rgba, window_id="Src")
    before = len(app.windows)
    assert app.apply(ExtractAlphaChannels(mode="extract")) is True
    assert len(app.windows) == before + 1  # creates_window read off the instance
    assert app.windows[-1].main_view.image.channels == 1


# --- RGBA raster export ----------------------------------------------------------
def test_png_rgba_round_trip(tmp_path) -> None:
    from retina.io.raster import load_raster, save_raster

    rgba = CreateAlphaChannels(mode="constant", value=0.5).execute_on_image(Image(_rgb_star(12, 9)))
    path = str(tmp_path / "out.png")
    save_raster(path, rgba)
    reread = load_raster(path)
    assert reread.shape == (9, 12, 4)
    assert float(reread[0, 0, 3]) == pytest.approx(0.5, abs=1 / 255)


def test_jpeg_flattens_the_alpha(tmp_path) -> None:
    from retina.io.raster import load_raster, save_raster

    rgba = CreateAlphaChannels(mode="constant", value=0.5).execute_on_image(Image(_rgb_star(12, 9)))
    path = str(tmp_path / "out.jpg")
    save_raster(path, rgba)  # does not raise: flattened onto the nominal channels
    assert load_raster(path).shape[2] == 3


# --- FindingChart ------------------------------------------------------------------
def _resolved_window(app):
    """64×48 window with a hand-made TAN WCS (1″/px, roughly centred on M31)."""
    from astropy.wcs import WCS

    win = app.new_window(Image(_rgb_star(64, 48)), window_id="Field")
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crval = [10.68, 41.27]
    wcs.wcs.crpix = [32.0, 24.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    win.wcs = wcs
    return win


def test_findingchart_produces_a_solved_window() -> None:
    from retina.app import Application
    from retina.processes.astrometry import FindingChart

    app = Application()
    _resolved_window(app)
    chart = FindingChart(size=256, catalog="none")
    assert app.run(chart) is True

    window = next(w for w in app.windows if w.id == "Field_FindingChart")
    image = window.main_view.image
    assert image.width == 256 and image.height == 256 and image.channels == 3
    assert window.wcs is not None  # the chart is itself solved
    # the chart is not uniform: grid + footprint have been drawn
    assert float(image.data.std()) > 0.0


def test_findingchart_with_supplied_stars_headless() -> None:
    from retina.app import Application
    from retina.processes.astrometry import FindingChart

    app = Application()
    _resolved_window(app)
    empty = FindingChart(size=192, catalog="none", new_image_id="NoStars")
    app.run(empty)
    with_stars = FindingChart(size=192, catalog="none", new_image_id="WithStars")
    # one bright star right at the centre of the field
    with_stars.set_objects([(10.68, 41.27, 3.0)])
    app.run(with_stars)

    without_img = next(w for w in app.windows if w.id == "NoStars").main_view.image
    with_img = next(w for w in app.windows if w.id == "WithStars").main_view.image
    assert float(with_img.data.sum()) > float(without_img.data.sum())


def test_findingchart_without_wcs_raises() -> None:
    from retina.app import Application
    from retina.processes.astrometry import FindingChart

    app = Application()
    app.new_window(Image(_rgb_star(16, 16)), window_id="Raw")
    with pytest.raises(ValueError):
        app.run(FindingChart(catalog="none"))
