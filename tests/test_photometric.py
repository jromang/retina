"""Photometric colour calibration (PCC) — recovers an injected colour cast."""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image, get
from retina.model.window import ImageWindow


def _synthetic_wcs(h, w):
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [w / 2, h / 2]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def test_pcc_recovers_injected_color_cast():
    h = w = 128
    star_px = [(20, 20), (100, 30), (60, 64), (40, 100), (95, 105), (30, 70)]
    base = np.full((h, w, 3), 0.02, dtype=np.float32)
    ys, xs = np.mgrid[0:h, 0:w]
    for (cx, cy) in star_px:
        blob = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 2.0**2))).astype(np.float32)
        for c in range(3):  # NEUTRAL stars (equal flux in the 3 channels)
            base[:, :, c] += 0.7 * blob
    base = np.clip(base, 0, 1)

    # colour cast: red channel ×1.5, blue ×0.8 (to be corrected)
    cast = base.copy()
    cast[:, :, 0] *= 1.5
    cast[:, :, 2] *= 0.8
    cast = np.clip(cast, 0, 1)

    win = ImageWindow(Image(cast))
    win.wcs = _synthetic_wcs(h, w)

    # synthetic catalogue: NEUTRAL stars (BP=G=RP=12) at the star positions
    catalog = []
    for (cx, cy) in star_px:
        sky = win.wcs.pixel_to_world(cx, cy)
        catalog.append((sky.ra.deg, sky.dec.deg, 12.0, 12.0, 12.0))

    proc = get("PhotometricColorCalibration")(aperture_radius=6.0, apply=True).set_catalog(catalog)
    proc.execute_on(win.main_view)

    # the gains must compensate the cast: R≈1/1.5, G=1, B≈1/0.8
    g = proc.gains
    assert g[1] == pytest.approx(1.0)
    assert g[0] == pytest.approx(1 / 1.5, rel=0.15)
    assert g[2] == pytest.approx(1 / 0.8, rel=0.15)

    # after calibration, the stellar colours are neutralised (R≈G at the peak)
    out = win.main_view.image.data
    cx, cy = star_px[0]
    r_over_g = out[cy, cx, 0] / max(out[cy, cx, 1], 1e-6)
    assert abs(r_over_g - 1.0) < 0.2


def test_pcc_requires_color_and_wcs():
    app = Application()
    win = app.new_window(Image(np.zeros((16, 16, 3), dtype=np.float32)))  # colour but no WCS
    with pytest.raises(ValueError):
        get("PhotometricColorCalibration")().set_catalog([]).execute_on(win.main_view)
