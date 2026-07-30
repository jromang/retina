"""Aperture photometry.

The test field carries **known** fluxes laid on a background **gradient**. Both matter:
without a known flux there would be no telling whether the measurement is right, and without
a gradient we would not see what the background annulus buys us — this is precisely the case
where subtracting a global background gets it wrong.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.model.window import ImageWindow
from retina.process.registry import get
from retina.processes.photometry import COLUMNS, PHOTOMETRY_TAG

pytest.importorskip("photutils")


def calibrated_field(size=300, gradient=0.10, noise=0.002, seed=9):
    """Twelve sources of known flux, on a background rising from left to right."""
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(seed)
    truth = np.zeros((size, size))
    positions, flux = [], []
    for i in range(12):
        y, x = 30 + (i // 4) * 90, 40 + (i % 4) * 70
        f = 5.0 * (i + 1)
        truth[y, x] += f
        positions.append((x, y))
        flux.append(f)
    image = gaussian_filter(truth, 2.0)
    _, xx = np.mgrid[0:size, 0:size]
    image = image + 0.05 + gradient * (xx / size) + rng.normal(0, noise, (size, size))
    return Image(image[:, :, None].astype(np.float32)), positions, flux


SETTINGS = {"fwhm": 4.0, "aperture_radius": 8.0, "annulus_inner": 12.0,
            "annulus_outer": 18.0, "threshold_sigma": 6.0}


def match_sources(measures, positions, flux):
    """Pair every measurement with the nearest true source."""
    pairs = []
    for s in measures:
        i = min(range(len(positions)),
                key=lambda k: (positions[k][0] - s["x"]) ** 2 + (positions[k][1] - s["y"]) ** 2)
        pairs.append((s, flux[i]))
    return pairs


def test_the_measured_flux_is_the_true_flux_despite_the_gradient():
    image, positions, flux = calibrated_field()

    process = get("AperturePhotometry")(**SETTINGS)
    process.execute_on_image(image)

    assert process.result["n_sources"] >= 10
    for measure, true_flux in match_sources(process.result["sources"], positions, flux):
        assert measure["flux"] == pytest.approx(true_flux, rel=0.02)


def test_the_annulus_measures_the_background_where_the_source_is():
    """The background rises from left to right: the measurements must reflect it."""
    image, _, _ = calibrated_field(gradient=0.20)

    process = get("AperturePhotometry")(**SETTINGS)
    process.execute_on_image(image)

    sources = sorted(process.result["sources"], key=lambda s: s["x"])
    assert sources[-1]["background"] > sources[0]["background"] + 0.1


def test_an_annulus_that_is_not_one_raises():
    image, _, _ = calibrated_field()

    with pytest.raises(ValueError, match="ring"):
        get("AperturePhotometry")(aperture_radius=5.0, annulus_inner=12.0,
                                  annulus_outer=8.0).execute_on_image(image)


def test_sources_whose_annulus_overflows_are_discarded():
    """A partial background would give a wrong flux without saying so."""
    from scipy.ndimage import gaussian_filter

    data = np.zeros((120, 120))
    data[3, 3] = 50.0          # in the corner: its annulus falls outside the frame
    data[60, 60] = 50.0
    image = Image((gaussian_filter(data, 2.0) + 0.05)[:, :, None].astype(np.float32))

    process = get("AperturePhotometry")(**SETTINGS)
    process.execute_on_image(image)

    assert all(s["x"] > 18 and s["y"] > 18 for s in process.result["sources"])


def test_the_magnitude_follows_the_zero_point():
    image, _, _ = calibrated_field()

    without_zp = get("AperturePhotometry")(**SETTINGS)
    without_zp.execute_on_image(image)
    with_zp = get("AperturePhotometry")(**SETTINGS, zero_point=25.0)
    with_zp.execute_on_image(image)

    a = sorted(without_zp.result["sources"], key=lambda s: -s["flux"])[0]
    b = sorted(with_zp.result["sources"], key=lambda s: -s["flux"])[0]
    assert b["magnitude"] == pytest.approx(a["magnitude"] + 25.0, abs=1e-6)
    # A source twice as bright is 0.753 magnitude "smaller".
    assert a["magnitude"] < 0


def test_the_signal_to_noise_ratio_follows_the_flux():
    image, _, _ = calibrated_field()

    process = get("AperturePhotometry")(**SETTINGS)
    process.execute_on_image(image)

    by_flux = sorted(process.result["sources"], key=lambda s: s["flux"])
    assert by_flux[0]["snr"] < by_flux[-1]["snr"]
    assert all(s["flux_error"] > 0 for s in by_flux)


def test_the_csv_export_is_a_domain_gesture(tmp_path):
    """It has to work from the console, with no interface — that is the parity rule."""
    image, _, _ = calibrated_field()
    target = tmp_path / "sub" / "photometry.csv"

    process = get("AperturePhotometry")(**SETTINGS, output_path=str(target))
    process.execute_on_image(image)

    assert target.exists()
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == ",".join(COLUMNS)
    assert len(lines) - 1 == process.result["n_sources"]


def test_the_celestial_coordinates_arrive_when_the_field_is_solved():
    from astropy.wcs import WCS

    image, _, _ = calibrated_field()
    window = ImageWindow(image)
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [150, 150]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    window.wcs = wcs

    process = get("AperturePhotometry")(**SETTINGS)
    process.execute_on(window.main_view)

    assert all(s["ra"] is not None for s in process.result["sources"])
    assert 149 < process.result["sources"][0]["ra"] < 151


def test_without_wcs_the_celestial_coordinates_are_absent_not_invented():
    image, _, _ = calibrated_field()

    process = get("AperturePhotometry")(**SETTINGS)
    process.execute_on_image(image)

    assert all(s["ra"] is None and s["dec"] is None for s in process.result["sources"])


def test_the_apertures_are_drawn_on_request():
    image, _, _ = calibrated_field()
    window = ImageWindow(image)

    get("AperturePhotometry")(**SETTINGS, show_apertures=True).execute_on(window.main_view)

    frames = [o for o in window.viewport.overlays if o.get("tag") == PHOTOMETRY_TAG]
    assert frames and frames[0]["kind"] == "ellipses"


def test_an_empty_field_returns_an_empty_table_not_an_error():
    rng = np.random.default_rng(0)
    flat = Image((np.full((128, 128, 1), 0.05)
                  + rng.normal(0, 1e-4, (128, 128, 1))).astype(np.float32))

    process = get("AperturePhotometry")(**SETTINGS)
    process.execute_on_image(flat)

    assert process.result["n_sources"] == 0
    assert process.result["sources"] == []
