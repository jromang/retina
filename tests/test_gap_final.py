"""Tests for the last batch of gap-closing processes: AdaptiveStretch,
MultiscaleAdaptiveStretch, GradientHDR (Compression/Composition), Gaia/APASS catalogs.
All headless.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image, get
from retina.io.fits import save_fits
from retina.model.window import ImageWindow


def _galaxy(h=64, w=64, core_sigma=3.0, halo_sigma=16.0):
    """Compact bright core + broad faint halo + background — a typical HDR case."""
    ys, xs = np.mgrid[0:h, 0:w]
    r2 = (xs - w / 2) ** 2 + (ys - h / 2) ** 2
    core = 0.9 * np.exp(-r2 / (2 * core_sigma**2))
    halo = 0.2 * np.exp(-r2 / (2 * halo_sigma**2))
    return np.clip(core + halo + 0.03, 0, 1).astype(np.float32)[:, :, None]


def _synthetic_wcs(h, w):
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [w / 2, h / 2]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


# --- AdaptiveStretch ----------------------------------------------------------
def test_adaptive_stretch_expands_dynamic_range():
    # low-dynamic-range image (compressed values) → the stretch must open the histogram up
    data = (_galaxy() * 0.3 + 0.1).astype(np.float32)
    out = get("AdaptiveStretch")(noise_threshold=1e-3).execute_on_image(Image(data)).data
    assert (out.max() - out.min()) > (data.max() - data.min())


def test_adaptive_stretch_is_monotonic():
    rs = np.random.RandomState(0)
    data = rs.rand(32, 32, 1).astype(np.float32)
    out = get("AdaptiveStretch")().execute_on_image(Image(data)).data
    order_in = np.argsort(data.ravel())
    mapped = out.ravel()[order_in]
    assert np.all(np.diff(mapped) >= -1e-6)  # order preserved → monotonic curve


def test_adaptive_stretch_noise_threshold_tempers():
    data = (_galaxy() * 0.3 + 0.1).astype(np.float32)
    soft = get("AdaptiveStretch")(noise_threshold=1e-4).execute_on_image(Image(data)).data
    hard = get("AdaptiveStretch")(noise_threshold=0.3).execute_on_image(Image(data)).data
    # high threshold → nearly everything is "noise" → gentler stretch (less local contrast)
    assert hard.std() <= soft.std() + 1e-6


# --- MultiscaleAdaptiveStretch ------------------------------------------------
def test_multiscale_adaptive_stretch_preserves_detail():
    data = (_galaxy() * 0.4 + 0.05).astype(np.float32)
    out = get("MultiscaleAdaptiveStretch")(detail_boost=1.5).execute_on_image(Image(data)).data
    assert out.shape == data.shape and np.isfinite(out).all()
    assert (out.max() - out.min()) > (data.max() - data.min())  # tonality stretched


# --- GradientHDRCompression ---------------------------------------------------
def test_gradient_hdr_compression_lifts_faint_halo():
    data = _galaxy()
    out = get("GradientHDRCompression")(beta=0.6).execute_on_image(Image(data)).data
    h, w = data.shape[:2]
    core = slice(h // 2 - 1, h // 2 + 2), slice(w // 2 - 1, w // 2 + 2)
    halo_y, halo_x = h // 2, w // 2 + 20  # a point in the faint halo
    ratio_in = data[halo_y, halo_x, 0] / data[core][:, :, 0].mean()
    ratio_out = out[halo_y, halo_x, 0] / out[core][:, :, 0].mean()
    assert ratio_out > ratio_in  # the halo is lifted relative to the core (HDR compression)


# --- GradientHDRComposition (global) ------------------------------------------
def test_gradient_hdr_composition_creates_window(tmp_path):
    scene = _galaxy(40, 40)
    p1, p2 = tmp_path / "short.fits", tmp_path / "long.fits"
    save_fits(str(p1), Image(np.clip(scene * 0.5, 0, 1)))
    save_fits(str(p2), Image(np.clip(scene * 1.5, 0, 1)))
    app = Application()
    app.run(get("GradientHDRComposition")(frames=[str(p1), str(p2)], new_image_id="ghdr"))
    out = app.windows[-1].main_view.image.data
    assert out.shape == (40, 40, 1) and np.isfinite(out).all()


# --- Gaia / APASS catalogs ----------------------------------------------------
def test_gaia_catalog_projects_field_stars():
    win = ImageWindow(Image(np.zeros((40, 40, 1), np.float32)))
    win.wcs = _synthetic_wcs(40, 40)
    catalog = [
        (150.0, 2.0, 10.0),        # center → inside the field
        (150.005, 2.005, 11.0),    # near center → inside the field
        (149.99, 1.99, 12.0),      # near center → inside the field
        (160.0, 2.0, 9.0),         # far away → outside the field
    ]
    proc = get("GaiaCatalog")().set_catalog(catalog)
    proc.execute_on(win.main_view)
    assert proc.result["n_stars"] == 3
    assert all("x" in s and "y" in s for s in proc.result["stars"])


def test_apass_catalog_shares_projection():
    win = ImageWindow(Image(np.zeros((40, 40, 1), np.float32)))
    win.wcs = _synthetic_wcs(40, 40)
    proc = get("APASSCatalog")().set_catalog([(150.0, 2.0, 13.0), (155.0, 5.0, 12.0)])
    proc.execute_on(win.main_view)
    assert proc.result["n_stars"] == 1  # only the central star falls inside the field


def test_catalog_requires_wcs():
    win = ImageWindow(Image(np.zeros((16, 16, 1), np.float32)))  # no WCS
    with pytest.raises(ValueError):
        get("GaiaCatalog")().set_catalog([(150.0, 2.0, 10.0)]).execute_on(win.main_view)
