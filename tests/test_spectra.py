"""Spectral curves and SPCC on real spectra.

No test touches the network: the spectra are synthesised (blackbodies, emission lines) and
injected through ``set_catalog``. What is checked is that the whole chain — curve → channel
response → synthetic flux → gain — recovers a colour drift **we introduced on purpose**, which
is the only way to know whether the assembly runs in the right direction.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import spectra
from retina.model.image import Image
from retina.model.window import ImageWindow
from retina.process.registry import get
from retina.processes.photometric import SPECTRAL_GRID

pytest.importorskip("photutils")


# --- the curve database ---------------------------------------------------------------

def test_the_three_families_are_bundled():
    for family in ("filter", "sensor", "white_reference"):
        assert spectra.list_curves(family), f"no {family} curve bundled"


def test_every_bundled_curve_cites_its_source_and_licence():
    """The database comes from a third-party GPL-3 project: crediting it is not a courtesy."""
    for info in spectra.list_curves():
        assert info.name, f"{info.id}: no name"
        assert info.source, f"{info.id}: no source"
        assert info.license, f"{info.id}: no licence"


def test_transmissions_and_efficiencies_are_normalised_to_fractions():
    """Manufacturer datasheets mix percentages and fractions; we do not."""
    for family in ("filter", "sensor"):
        for info in spectra.list_curves(family):
            curve = spectra.load_curve(info.id, family)
            assert curve[:, 1].max() <= 1.5, f"{info.id}: still in percent?"
            assert curve[:, 1].min() >= 0.0


def test_curves_are_sorted_and_increasing_in_wavelength():
    for info in spectra.list_curves():
        lam = spectra.load_curve(info.id, info.kind)[:, 0]
        assert np.all(np.diff(lam) >= 0)


def test_a_channel_response_peaks_where_its_filter_peaks():
    """The dumbest and most useful check there is: R, G and B, in that order."""
    peaks = [
        SPECTRAL_GRID[int(np.argmax(spectra.channel_response(f, s, SPECTRAL_GRID)))]
        for f, s in (("baader_r", "sony_imx571_red"), ("baader_g", "sony_imx571_green"),
                     ("baader_b", "sony_imx571_blue"))
    ]
    assert peaks[0] > peaks[1] > peaks[2]
    assert 590 < peaks[0] < 660 and 500 < peaks[1] < 560 and 430 < peaks[2] < 500


def test_outside_its_support_a_curve_transmits_nothing():
    """Extending by the edge value would invent an infrared tail for the filter."""
    curve = spectra.load_curve("baader_b", "filter")
    far = spectra.resample(curve, np.array([200.0, 2000.0]))

    assert np.all(far == 0.0)


def test_a_boxcar_only_passes_its_own_band():
    response = spectra.boxcar_response(656.3, 7.0, SPECTRAL_GRID)
    inside = SPECTRAL_GRID[response > 0]

    assert inside.min() >= 652.0 and inside.max() <= 660.0


def test_a_user_curve_shadows_the_bundled_one():
    points = [(400.0, 0.1), (500.0, 0.9), (600.0, 0.1)]
    spectra.save_user_curve("baader_r", "filter", points, label="My Baader R")
    try:
        info = spectra.curve_info("baader_r", "filter")
        assert info.user and info.name == "My Baader R"
        curve = spectra.load_curve("baader_r", "filter")
        assert len(curve) == 3
        # A single entry in the list: the one that will be loaded, not both.
        assert sum(1 for c in spectra.list_curves("filter") if c.id == "baader_r") == 1
    finally:
        assert spectra.delete_user_curve("baader_r", "filter")
    assert not spectra.curve_info("baader_r", "filter").user  # the bundled one is back


def test_an_unknown_curve_says_what_does_exist():
    with pytest.raises(KeyError, match="available"):
        spectra.load_curve("not_a_filter", "filter")


# --- the SPCC ------------------------------------------------------------------------

def synthetic_wcs(h, w):
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [w / 2, h / 2]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def blackbody(temperature: float) -> np.ndarray:
    """Planck spectrum on the working grid, in arbitrary units."""
    lam = SPECTRAL_GRID * 1e-9
    h, c, k = 6.62607015e-34, 2.99792458e8, 1.380649e-23
    intensity = (2 * h * c**2) / lam**5 / np.expm1(h * c / (lam * k * temperature))
    return intensity / intensity.max()


def field(h, w, positions, color=(1.0, 1.0, 1.0)):
    base = np.full((h, w, 3), 0.02, dtype=np.float32)
    ys, xs = np.mgrid[0:h, 0:w]
    for cx, cy in positions:
        blob = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 2.0**2))).astype(np.float32)
        for c in range(3):
            base[:, :, c] += 0.7 * color[c] * blob
    return np.clip(base, 0, 1)


FILTERS = {
    "red_filter": "baader_r", "green_filter": "baader_g", "blue_filter": "baader_b",
    "red_sensor": "sony_imx571_red", "green_sensor": "sony_imx571_green",
    "blue_sensor": "sony_imx571_blue",
}


def test_the_spectral_spcc_recovers_an_injected_colour_drift():
    """End to end: real curves, real spectra, a known drift to recover."""
    h = w = 128
    stars = [(20, 20), (100, 30), (60, 64), (40, 100), (95, 105), (30, 70)]
    drift = (1.5, 1.0, 0.8)
    win = ImageWindow(Image(field(h, w, stars, drift)))
    win.wcs = synthetic_wcs(h, w)

    # Every star shares the same spectrum: the "correct" image would render them in the
    # proportions dictated by the channel responses, and the drift is what departs from that.
    spectrum = blackbody(5800.0)
    catalog = []
    for cx, cy in stars:
        sky = win.wcs.pixel_to_world(cx, cy)
        catalog.append({"ra": sky.ra.deg, "dec": sky.dec.deg,
                          "bp": 12.0, "g": 12.0, "rp": 12.0, "spectrum": spectrum})

    process = get("SpectrophotometricColorCalibration")(
        aperture_radius=6.0, apply=False, white_reference="", **FILTERS)
    process.set_catalog(catalog).execute_on(win.main_view)

    assert process.n_spectra == len(stars)   # the spectral path really was used
    report = process.gains / process.gains[1]
    assert report[0] == pytest.approx(1 / 1.5, rel=0.2)
    assert report[2] == pytest.approx(1 / 0.8, rel=0.2)


def test_without_named_curves_the_spcc_keeps_its_original_behaviour():
    """Three identical responses would yield the same flux three times: the silent no-op is
    what we refuse. Without curves, we fall back on the nominal passbands."""
    process = get("SpectrophotometricColorCalibration")()

    assert not process.has_response()
    assert get("SpectrophotometricColorCalibration")(**FILTERS).has_response()
    assert get("SpectrophotometricColorCalibration")(narrowband=True).has_response()


def test_narrowband_mode_only_looks_at_its_own_bands():
    process = get("SpectrophotometricColorCalibration")(
        narrowband=True, red_wavelength=656.3, red_bandwidth=7.0,
        green_wavelength=500.7, green_bandwidth=7.0,
        blue_wavelength=486.1, blue_bandwidth=7.0)

    responses = process.responses()

    assert responses.shape == (3, len(SPECTRAL_GRID))
    for channel, centre in enumerate((656.3, 500.7, 486.1)):
        active = SPECTRAL_GRID[responses[channel] > 0]
        assert abs(active.mean() - centre) < 4.0


def test_the_white_reference_changes_the_gains():
    """It is what *defines* neutral: removing it has to show."""
    h = w = 128
    stars = [(20, 20), (100, 30), (60, 64), (40, 100), (95, 105), (30, 70)]
    win = ImageWindow(Image(field(h, w, stars)))
    win.wcs = synthetic_wcs(h, w)
    spectrum = blackbody(5800.0)
    catalog = [
        {"ra": win.wcs.pixel_to_world(cx, cy).ra.deg,
         "dec": win.wcs.pixel_to_world(cx, cy).dec.deg,
         "bp": 12.0, "g": 12.0, "rp": 12.0, "spectrum": spectrum}
        for cx, cy in stars
    ]

    def gains(white):
        p = get("SpectrophotometricColorCalibration")(
            aperture_radius=6.0, apply=False, white_reference=white, **FILTERS)
        p.set_catalog(list(catalog)).execute_on(win.main_view)
        return p.gains

    flat = gains("")
    galaxy = gains("average_spiral_galaxy")
    assert not np.allclose(flat, galaxy, rtol=0.02)


def test_the_old_catalog_form_still_works():
    """A recipe written before this change passes tuples: it has to keep running."""
    h = w = 128
    stars = [(20, 20), (100, 30), (60, 64), (40, 100), (95, 105), (30, 70)]
    win = ImageWindow(Image(field(h, w, stars, (1.5, 1.0, 0.8))))
    win.wcs = synthetic_wcs(h, w)
    catalog = [(win.wcs.pixel_to_world(cx, cy).ra.deg,
                  win.wcs.pixel_to_world(cx, cy).dec.deg, 12.0, 12.0, 12.0)
                 for cx, cy in stars]

    process = get("SpectrophotometricColorCalibration")(aperture_radius=6.0, apply=False)
    process.set_catalog(catalog).execute_on(win.main_view)

    assert process.n_spectra == 0
    assert process.gains[0] == pytest.approx(1 / 1.5, rel=0.2)


# --- FilterManager --------------------------------------------------------------------

def test_filter_manager_lists_shows_adds_and_removes():
    from retina.app import Application

    app = Application()
    manager = get("FilterManager")

    list_action = manager(action="list", kind="filter")
    list_action.execute_global(app)
    assert list_action.result["curves"] and all("id" in c for c in list_action.result["curves"])

    show_action = manager(action="show", kind="filter", name="baader_r")
    show_action.execute_global(app)
    assert len(show_action.result["wavelength_nm"]) == len(show_action.result["value"]) > 2

    add_item = manager(action="add", kind="filter", name="retina_trial",
                      label="Trial", points=[400.0, 0.1, 500.0, 0.9, 600.0, 0.2])
    add_item.execute_global(app)
    assert spectra.curve_info("retina_trial", "filter").user

    remove_item = manager(action="remove", kind="filter", name="retina_trial")
    remove_item.execute_global(app)
    assert remove_item.result["removed"]
    with pytest.raises(KeyError):
        spectra.curve_info("retina_trial", "filter")


def test_filter_manager_refuses_to_remove_a_bundled_curve():
    from retina.app import Application

    with pytest.raises(ValueError, match="cannot be removed"):
        get("FilterManager")(action="remove", kind="filter",
                             name="baader_r").execute_global(Application())


# --- the SPCC form offers the base instead of asking for its names -------------------------

def test_spcc_offers_the_bundled_curves_as_choices():
    """Six of SPCC's parameters used to be free text, over 54 curves whose identifiers are
    file stems. A wrong name does not fail — it falls back on the nominal passbands, which is
    the pre-SPCC behaviour, so the calibration looks like it ran."""
    spcc = get("SpectrophotometricColorCalibration")

    filters = spcc.parameter_choices("red_filter")
    sensors = spcc.parameter_choices("green_sensor")
    whites = spcc.parameter_choices("white_reference")

    assert "baader_r" in filters and "sony_imx571_green" in sensors
    # Empty stays offered for filters and sensors: "no curve for my rig" is legitimate, and it
    # is what the process did before this base existed.
    assert filters[0] == "" and sensors[0] == ""
    # Not for the white reference: it is what *defines* the neutral, there is no fallback.
    assert "" not in whites
    assert spcc().white_reference in whites
    assert spcc.parameter_choices("mag_faint") is None


def test_spcc_choices_follow_a_user_curve(tmp_path, monkeypatch):
    """Read on every projection of the schema, so a curve dropped in shows up without a
    restart — the reason these are not static `choices`."""
    monkeypatch.setattr(spectra, "config_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    spectra.save_user_curve("my_scope", "filter", [[400.0, 0.1], [700.0, 0.9]], label="Mine")

    assert "my_scope" in get("SpectrophotometricColorCalibration").parameter_choices("blue_filter")


def test_spcc_hides_the_mode_that_does_not_apply():
    """The seven narrowband fields used to show at all times, next to the six broadband
    pickers they exclude: twenty controls of which half were inert."""
    params = {p.id: p for p in get("SpectrophotometricColorCalibration").parameters}

    assert params["red_wavelength"].visible_when == ("narrowband", (True,))
    assert params["red_filter"].visible_when == ("narrowband", (False,))
    # The white reference belongs to both modes.
    assert params["white_reference"].visible_when is None
