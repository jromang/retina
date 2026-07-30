"""Tier 1-3 tests: DynamicAlignment, SPCC, flux calibration, B3E, ICC, raster, Blink, ephemerides.

All headless. SPCC and flux calibration use a synthetic WCS plus an injected catalogue
(``set_catalog``), just like the PCC tests.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Image, get
from retina.io.fits import save_fits
from retina.model.window import ImageWindow
from retina.process import context


@pytest.fixture
def provider():
    store: dict[str, Image] = {}
    context.set_image_provider(lambda name: store.get(name))
    yield store
    context.set_image_provider(None)


def _synthetic_wcs(h, w):
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [w / 2, h / 2]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def _star_field(h, w, star_px, color=(1.0, 1.0, 1.0)):
    base = np.full((h, w, 3), 0.02, dtype=np.float32)
    ys, xs = np.mgrid[0:h, 0:w]
    for (cx, cy) in star_px:
        blob = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 2.0 ** 2))).astype(np.float32)
        for c in range(3):
            base[:, :, c] += 0.7 * color[c] * blob
    return np.clip(base, 0, 1)


# --- Tier 1: DynamicAlignment -------------------------------------------------
def test_dynamic_alignment_recovers_translation():
    data = np.zeros((40, 40, 1), np.float32)
    data[12, 12, 0] = 1.0
    src = [12, 12, 25, 18, 8, 30]
    dst = [17, 12, 30, 18, 13, 30]  # translation of +5 px in x
    out = get("DynamicAlignment")(
        source=src, target=dst, mode="affine"
    ).execute_on_image(Image(data)).data
    py, px = np.unravel_index(int(np.argmax(out[:, :, 0])), out.shape[:2])
    assert (py, px) == (12, 17)


def test_dynamic_alignment_needs_matching_points():
    with pytest.raises(ValueError):
        get("DynamicAlignment")(source=[0, 0], target=[1, 1, 2, 2]).execute_on_image(
            Image(np.zeros((8, 8, 1), np.float32)))


# --- Tier 1/2: SPCC & flux calibration ----------------------------------------
def test_spcc_recovers_injected_color_cast():
    h = w = 128
    star_px = [(20, 20), (100, 30), (60, 64), (40, 100), (95, 105), (30, 70)]
    cast = _star_field(h, w, star_px, color=(1.5, 1.0, 0.8))  # drift R×1.5, B×0.8
    win = ImageWindow(Image(cast))
    win.wcs = _synthetic_wcs(h, w)
    catalog = []  # neutral stars, BP=G=RP=12
    for (cx, cy) in star_px:
        sky = win.wcs.pixel_to_world(cx, cy)
        catalog.append((sky.ra.deg, sky.dec.deg, 12.0, 12.0, 12.0))
    proc = get("SpectrophotometricColorCalibration")(aperture_radius=6.0).set_catalog(catalog)
    proc.execute_on(win.main_view)
    g = proc.gains
    assert g[1] == pytest.approx(1.0)
    assert g[0] == pytest.approx(1 / 1.5, rel=0.2)
    assert g[2] == pytest.approx(1 / 0.8, rel=0.2)


def test_flux_calibration_scales_with_signal():
    h = w = 128
    star_px = [(20, 20), (100, 30), (60, 64), (40, 100), (95, 105)]
    field = _star_field(h, w, star_px)
    win1 = ImageWindow(Image(field))
    win1.wcs = _synthetic_wcs(h, w)
    win2 = ImageWindow(Image(np.clip(field * 0.5, 0, 1)))  # half the signal
    win2.wcs = _synthetic_wcs(h, w)
    cat = []
    for (cx, cy) in star_px:
        sky = win1.wcs.pixel_to_world(cx, cy)
        cat.append((sky.ra.deg, sky.dec.deg, 12.0, 12.0, 12.0))
    zp1 = get("SpectrophotometricFluxCalibration")(
        aperture_radius=6.0
    ).set_catalog(cat)._compute(win1.main_view)
    zp2 = get("SpectrophotometricFluxCalibration")(
        aperture_radius=6.0
    ).set_catalog(cat)._compute(win2.main_view)
    assert zp1 > 0 and zp2 > 0
    assert zp2 == pytest.approx(2 * zp1, rel=0.1)  # less flux → zero point ×2


# --- Tier 3: B3Estimator ------------------------------------------------------
def test_b3_estimator_subtracts_continuum(provider, rng):
    cont = Image((rng.random((16, 16, 1)) * 0.4).astype(np.float32))
    provider["cont"] = cont
    proc = get("B3Estimator")(continuum="cont", pedestal=0.05)
    res = proc.execute_on_image(Image(cont.data.copy())).data  # narrowband == continuum
    assert proc.k == pytest.approx(1.0, rel=0.2)
    assert abs(float(res.mean()) - 0.05) < 0.03  # ≈ pedestal (null emission line)


# --- Tier 3: ICC --------------------------------------------------------------
def test_icc_srgb_roundtrip_is_near_identity(rng):
    rgb = Image(rng.random((8, 8, 3)).astype(np.float32))
    out = get("ICCProfileTransformation")(
        from_profile="sRGB", to_profile="sRGB"
    ).execute_on_image(rgb).data
    assert np.abs(out - rgb.data).max() < 0.01  # sRGB→sRGB ≈ identity (8-bit rounding)


def test_assign_icc_profile_sets_metadata():
    win = ImageWindow(Image(np.zeros((4, 4, 3), np.float32)))
    get("AssignICCProfile")(profile="sRGB").execute_on(win.main_view)
    assert win.icc_profile == "sRGB"


# --- Tier 2: raster export ----------------------------------------------------
def test_raster_roundtrip(tmp_path, rng):
    from retina.io import load_image_array, save_image

    rgb = Image(rng.random((8, 8, 3)).astype(np.float32))
    tif = str(tmp_path / "x.tif")
    save_image(tif, rgb)
    assert np.abs(load_image_array(tif) - rgb.data).max() < 1e-6  # float TIFF, exact
    png = str(tmp_path / "x.png")
    save_image(png, rgb)
    assert np.abs(load_image_array(png) - rgb.data).max() < 0.01  # 8-bit PNG

    # JPEG2000: 16-bit greyscale (near exact) and 8-bit colour, lossless (OpenJPEG)
    gray = Image(rng.random((8, 8, 1)).astype(np.float32))
    jp2_gray = str(tmp_path / "g.jp2")
    save_image(jp2_gray, gray)
    assert np.abs(load_image_array(jp2_gray) - gray.data).max() < 1e-3  # 16-bit greyscale
    jp2_rgb = str(tmp_path / "c.jp2")
    save_image(jp2_rgb, rgb)
    assert np.abs(load_image_array(jp2_rgb) - rgb.data).max() < 0.01  # 8-bit colour


# --- Tier 2: Blink ------------------------------------------------------------
def test_blink_loads_and_navigates(tmp_path):
    paths = []
    for i in range(3):
        p = str(tmp_path / f"b{i}.fits")
        save_fits(p, Image(np.full((8, 8, 1), 0.1 * (i + 1), np.float32)))
        paths.append(p)
    bl = get("Blink")(frames=paths)

    # `load` describes the sequence without reading a single pixel: a hundred 50 Mpx frames do
    # not fit in memory, and looking at three images must not pay the price of the other
    # ninety-seven. The statistics come as you visit them.
    described = bl.load()
    assert [d["name"] for d in described] == ["b0.fits", "b1.fits", "b2.fits"]
    assert all("median" not in d for d in described)
    assert bl.stats == [None, None, None]

    assert [round(bl.stats_at(i)["median"], 2) for i in range(3)] == [0.1, 0.2, 0.3]
    assert bl.step() == 1 and bl.step() == 2 and bl.step() == 0  # wraps around
    assert bl.current_image().data.shape == (8, 8, 1)


# --- Tier 3: EphemerisGenerator ----------------------------------------------
def test_ephemeris_generator_produces_track():
    proc = get("EphemerisGenerator")(body="mars", start="2026-01-01T00:00:00",
                                      step_hours=24.0, count=5)
    rows = proc.generate()
    assert len(rows) == 5
    for r in rows:
        assert 0.0 <= r["ra_deg"] <= 360.0 and -90.0 <= r["dec_deg"] <= 90.0
    # Mars moves: RA differs between the first and the last point
    assert rows[0]["ra_deg"] != rows[-1]["ra_deg"]


@pytest.fixture
def rng():
    return np.random.default_rng(7)


def test_ephemeris_publishes_a_dict():
    """`server/jobs.py::_result_de` publishes only `.result`, and only if it is a dict:
    the table stored in `.ephemeris` therefore **never** reached the client."""
    proc = get("EphemerisGenerator")(body="mars", start="2026-01-01T00:00:00", count=3)
    proc.generate()

    assert isinstance(proc.result, dict)
    assert proc.result["n_points"] == 3
    assert proc.result["ephemeris"] is proc.ephemeris  # the console keeps its access


def test_ephemeris_passes_on_the_kernel_choice(monkeypatch):
    """Downloading DE440s is not testable in CI: we check the plumbing instead.

    The parameter name has a history: called `ephemeris`, it collided with `self.ephemeris`,
    which carries the produced table — the process then asked astropy for a kernel named "[]".
    """
    import contextlib

    import astropy.coordinates as coords

    requested = []

    class FakeState:
        @staticmethod
        def set(name):
            requested.append(name)
            return contextlib.nullcontext()  # leaves astropy's global state alone

    monkeypatch.setattr(coords, "solar_system_ephemeris", FakeState)
    get("EphemerisGenerator")(body="mars", kernel="de440s", count=2).generate()

    assert requested == ["de440s"]


def test_a_small_body_goes_through_horizons(monkeypatch):
    """Neither ERFA nor the DE kernels know about asteroids: Horizons is the only route."""
    import astroquery.jplhorizons as jpl

    class FakeTable(dict):
        def __len__(self):
            return 2

    class FakeHorizons:
        def __init__(self, id, epochs):
            self.id, self.epochs = id, epochs

        def ephemerides(self):
            return FakeTable(RA=[10.0, 10.5], DEC=[20.0, 20.1], delta=[1.5, 1.51])

    monkeypatch.setattr(jpl, "Horizons", FakeHorizons)
    proc = get("EphemerisGenerator")(body="custom", custom_id="Ceres", count=2)

    rows = proc.generate()

    assert len(rows) == 2 and rows[1]["ra_deg"] == 10.5


def test_a_small_body_without_a_designation_raises():
    proc = get("EphemerisGenerator")(body="custom", count=2)
    with pytest.raises(ValueError, match="needs a small-body designation"):
        proc.generate()
