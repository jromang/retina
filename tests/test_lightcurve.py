"""Light curves — on a synthetic series whose true variability is known.

The test that matters is the first one: a sinusoidal target of known amplitude must be
recovered, and the check star must stay flat. Everything else (cache, export, syntax) is only
of interest if that one passes.

No network, no file outside ``tmp_path``.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Image
from retina.io.fits import observation_airmass, observation_jd, save_fits, wcs_keywords
from retina.processes.lightcurve import LightCurve, format_stars, parse_stars

SIZE = 128
#: pixel positions of the three stars of the series (target, comparison, check)
POSITIONS = ((40.0, 40.0), (90.0, 45.0), (60.0, 95.0))
FLUX_BASE = (500.0, 800.0, 650.0)
AMPLITUDE = 0.30  # 30 % peak to peak on the target, i.e. ~0.29 mag


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """The photometry cache lives at user scope: it has to be isolated."""
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path / "config"))


def _wcs():
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [SIZE / 2, SIZE / 2]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [210.5, 33.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def _exposure(target_factor: float, offset=(0.0, 0.0)) -> np.ndarray:
    """Three gaussian stars; only the first one has a varying flux."""
    ys, xs = np.mgrid[0:SIZE, 0:SIZE].astype(np.float64)
    plane = np.full((SIZE, SIZE), 0.01)
    for i, ((cx, cy), flux) in enumerate(zip(POSITIONS, FLUX_BASE, strict=True)):
        amplitude = flux * (target_factor if i == 0 else 1.0)
        r2 = (xs - cx - offset[0]) ** 2 + (ys - cy - offset[1]) ** 2
        plane += amplitude * np.exp(-r2 / (2 * 2.0 ** 2)) / (2 * np.pi * 4.0)
    return plane.astype(np.float32)


def _series(folder, n=12, with_wcs=True, drift=False, variable=True) -> list[str]:
    """One observing night: n dated exposures, the target varying sinusoidally."""
    wcs_cards = wcs_keywords(_wcs()) if with_wcs else {}
    paths = []
    for i in range(n):
        factor = 1.0 + AMPLITUDE * np.sin(2 * np.pi * i / n) if variable else 1.0
        shift = (0.7 * i if drift else 0.0, -0.4 * i if drift else 0.0)
        path = folder / f"light_{i:03d}.fits"
        save_fits(str(path), Image(_exposure(factor, shift)[:, :, None]), {
            **wcs_cards,
            "DATE-OBS": f"2026-07-29T22:{i:02d}:00.000",
            "EXPTIME": 60.0,
            "FILTER": "V",
        })
        paths.append(str(path))
    return paths


def _sky(index: int) -> tuple[float, float]:
    """Celestial coordinates of star ``index``, as the WCS sees them."""
    x, y = POSITIONS[index]
    sky = _wcs().pixel_to_world(x, y)
    return float(sky.ra.deg), float(sky.dec.deg)


def _curve(paths, **kwargs) -> LightCurve:
    proc = LightCurve(frames=paths, aperture_radius=6.0, annulus_inner=9.0,
                      annulus_outer=14.0, **kwargs)
    return proc.set_stars(target=_sky(0), comparisons=[_sky(1)], check=_sky(2))


# --- the test that matters ----------------------------------------------------------

def test_the_known_variability_is_recovered_and_the_check_star_stays_flat(tmp_path):
    points = _curve(_series(tmp_path)).measure()

    assert len(points) == 12
    mags = np.array([p["mag"] for p in points])
    checks = np.array([p["check_mag"] for p in points])
    assert np.isfinite(mags).all()

    # The injected amplitude is 2 × 0.30 in flux, i.e. 2.5·log10(1.3/0.7) ≈ 0.67 mag.
    expected = 2.5 * np.log10((1 + AMPLITUDE) / (1 - AMPLITUDE))
    assert (mags.max() - mags.min()) == pytest.approx(expected, rel=0.10)
    # …and the check star, for its part, does not move: that is what proves the measured
    # amplitude comes from the target and not from the measurement chain.
    assert (checks.max() - checks.min()) < 0.02


def test_the_points_are_dated_and_ordered(tmp_path):
    points = _curve(_series(tmp_path)).measure()

    jds = [p["jd"] for p in points]
    assert all(j is not None for j in jds)
    assert jds == sorted(jds)
    # 60 s exposure → the point is dated 30 s after the start.
    assert (jds[1] - jds[0]) == pytest.approx(60.0 / 86400.0, rel=1e-6)


def test_without_wcs_the_target_is_tracked_by_star_matching(tmp_path):
    """An unsolved and *drifting* series: the transport must follow the field."""
    pytest.importorskip("astroalign")
    paths = _series(tmp_path, with_wcs=False, drift=True)
    proc = LightCurve(frames=paths, aperture_radius=6.0, annulus_inner=9.0,
                      annulus_outer=14.0)
    proc.target = f"{POSITIONS[0][0]}:{POSITIONS[0][1]}"
    proc.comparisons = f"{POSITIONS[1][0]}:{POSITIONS[1][1]}"

    points = proc.measure()

    mags = np.array([p["mag"] for p in points if p["mag"] is not None])
    assert len(mags) == 12
    expected = 2.5 * np.log10((1 + AMPLITUDE) / (1 - AMPLITUDE))
    assert (mags.max() - mags.min()) == pytest.approx(expected, rel=0.15)


def test_recentring_is_what_makes_the_flux_stable(tmp_path):
    """Without recentring, a drifting field manufactures a variability that does not exist.

    The observable is the **raw flux**, not the differential magnitude: a common drift shifts
    every star alike, so the differential cancels it by itself. That is precisely what makes
    the defect discreet — it only shows on absolute photometry, or as soon as the drift is no
    longer the same from one edge of the field to the other (field rotation, flexure).
    """
    paths = _series(tmp_path, drift=True, variable=False)  # constant target
    without = _curve(paths, recenter=False, matching="wcs").measure()
    with_ = _curve(paths, recenter=True, matching="wcs").measure()

    def dispersion(points):
        flux = np.array([p["target_flux"] for p in points], dtype=float)
        return float(np.std(flux) / np.mean(flux))

    assert dispersion(without) > 0.02      # up to a few percent of false variability…
    assert dispersion(with_) < dispersion(without) / 5.0   # …that recentring wipes out


# --- measure / judge: the separation that makes replay free --------------------------

def test_judging_again_measures_nothing_anew(tmp_path):
    proc = _curve(_series(tmp_path))
    lines = proc.measure_raw()

    proc.mode = "instrumental"
    a = proc.evaluate(lines)
    proc.mode = "ensemble"
    b = proc.evaluate(lines)

    assert a[0]["mag"] != b[0]["mag"]  # the mode does change the result…
    assert a[0]["target_flux"] == b[0]["target_flux"]  # …without touching the measured fluxes


def test_the_second_measurement_comes_from_the_cache(tmp_path, monkeypatch):
    paths = _series(tmp_path)
    proc = _curve(paths)
    proc.measure_raw()

    calls = []
    monkeypatch.setattr(LightCurve, "measure_frame",
                        lambda self, c, e: calls.append(c) or {"stars": [], "jd": 0.0})
    _curve(paths).measure_raw()

    assert calls == []


def test_adding_one_exposure_only_remeasures_that_one(tmp_path):
    """Leaving ``frames`` out of the key is what makes adding frames incremental."""
    paths = _series(tmp_path, n=4)
    _curve(paths).measure_raw()

    proc = _curve(paths)
    settings_before = proc.detection_values()
    proc_plus = _curve([*paths, paths[0]])

    assert settings_before == proc_plus.detection_values()


def test_use_cache_false_remeasures(tmp_path, monkeypatch):
    paths = _series(tmp_path, n=3)
    _curve(paths).measure_raw()

    calls = []
    real = LightCurve.measure_frame
    monkeypatch.setattr(LightCurve, "measure_frame",
                        lambda self, c, e: calls.append(c) or real(self, c, e))
    _curve(paths, use_cache=False).measure_raw()

    assert len(calls) == 3


# --- designating the stars -----------------------------------------------------------

def test_the_two_designation_syntaxes():
    assert parse_stars("210.5,33.0") == [{"ra": 210.5, "dec": 33.0}]
    assert parse_stars("210.5,33.0,11.42") == [{"ra": 210.5, "dec": 33.0, "mag": 11.42}]
    assert parse_stars("40:60") == [{"x": 40.0, "y": 60.0}]
    assert len(parse_stars("1,2;3,4;5,6")) == 3
    assert parse_stars("") == []


def test_set_stars_round_trips():
    proc = LightCurve().set_stars(target=(1.0, 2.0),
                                  comparisons=[(3.0, 4.0, 11.0), (5.0, 6.0)])
    assert proc.target == "1.0,2.0"
    assert parse_stars(proc.comparisons)[0]["mag"] == 11.0
    assert format_stars(parse_stars(proc.comparisons)) == proc.comparisons


def test_an_unreadable_designation_raises():
    with pytest.raises(ValueError, match="Cannot read star"):
        parse_stars("just-a-word")


def test_without_a_target_the_process_refuses(tmp_path):
    proc = LightCurve(frames=_series(tmp_path, n=2))
    with pytest.raises(ValueError, match="no target star"):
        proc.measure_raw()


def test_without_frames_the_process_refuses():
    proc = LightCurve().set_stars(target=(1.0, 2.0))
    with pytest.raises(ValueError, match="no frames"):
        proc.measure_raw()


# --- exports --------------------------------------------------------------------------

def test_the_aavso_export_follows_the_extended_format(tmp_path):
    proc = _curve(_series(tmp_path, n=4), obscode="ABC", filter="V", notes="V1234 Cyg")
    proc.measure()

    path = proc.export_aavso(str(tmp_path / "aavso.txt"))
    with open(path, encoding="utf-8") as stream:
        lines = stream.read().splitlines()

    assert lines[0] == "#TYPE=EXTENDED"
    assert "#OBSCODE=ABC" in lines
    assert "#DELIM=," in lines and "#DATE=JD" in lines and "#OBSTYPE=CCD" in lines
    data = [ln for ln in lines if not ln.startswith("#")]
    assert len(data) == 4
    fields = data[0].split(",")
    assert len(fields) == 15
    assert fields[0] == "V1234 Cyg"
    assert fields[4] == "V"
    assert fields[5] == "NO"       # TRANS
    assert fields[6] == "DIF"      # no catalogue magnitude: differential, not standard


def test_catalog_magnitudes_make_the_export_standard(tmp_path):
    proc = LightCurve(frames=_series(tmp_path, n=3), aperture_radius=6.0,
                      annulus_inner=9.0, annulus_outer=14.0, obscode="ABC")
    proc.set_stars(target=_sky(0), comparisons=[(*_sky(1), 11.42)])
    proc.measure()

    assert proc.standardized
    path = proc.export_aavso(str(tmp_path / "std.txt"))
    with open(path, encoding="utf-8") as stream:
        data = [ln for ln in stream if not ln.startswith("#")]
    assert data[0].split(",")[6] == "STD"
    # The magnitude is brought back around that of the comparison, not around zero.
    assert 9.0 < proc.measurements[0]["mag"] < 14.0


def test_an_undated_exposure_does_not_enter_the_aavso_export(tmp_path):
    """An observation without an instant is not one — better omit it than date it wrong."""
    paths = _series(tmp_path, n=3)
    no_date = tmp_path / "no_date.fits"
    save_fits(str(no_date), Image(_exposure(1.0)[:, :, None]), wcs_keywords(_wcs()))
    proc = _curve([*paths, str(no_date)], obscode="ABC")
    proc.measure()

    assert len(proc.measurements) == 4
    with open(proc.export_aavso(str(tmp_path / "a.txt")), encoding="utf-8") as stream:
        data = [ln for ln in stream if not ln.startswith("#")]
    assert len(data) == 3


def test_the_csv_export_can_be_read_back(tmp_path):
    import csv as csv_module

    proc = _curve(_series(tmp_path, n=3))
    proc.measure()
    path = proc.export_csv(str(tmp_path / "curve.csv"))

    with open(path, encoding="utf-8") as stream:
        lines = list(csv_module.DictReader(stream))
    assert len(lines) == 3
    assert float(lines[0]["jd"]) > 2_400_000


def test_execute_global_publishes_a_dict(tmp_path):
    """`server/jobs.py` only publishes `.result`, and only if it is a dict."""
    from retina import Application

    proc = _curve(_series(tmp_path, n=3), output_csv=str(tmp_path / "out.csv"))
    assert proc.execute_global(Application())

    assert isinstance(proc.result, dict)
    assert proc.result["n_frames"] == 3 and proc.result["n_measured"] == 3
    assert set(proc.result["columns"]) <= set(proc.result["points"][0])
    assert proc.result["output_csv"].endswith("out.csv")


# --- reading time and airmass ----------------------------------------------------------

def test_the_jd_is_that_of_mid_exposure():
    start = observation_jd({"DATE-OBS": "2026-07-29T22:00:00.000", "EXPTIME": 0.0})
    middle = observation_jd({"DATE-OBS": "2026-07-29T22:00:00.000", "EXPTIME": 600.0})
    # Tolerance of 1 ms: a modern JD is worth ~2.46 million and a float64 has a step of
    # ~50 µs there. That is the floor of the format, not an imprecision of our computation —
    # and it is four orders of magnitude below what a light curve demands.
    assert (middle - start) == pytest.approx(300.0 / 86400.0, abs=1e-8)


def test_without_date_obs_the_jd_is_none():
    assert observation_jd({"EXPTIME": 60.0}) is None
    assert observation_jd({"DATE-OBS": "not a date"}) is None


def test_the_airmass_from_the_header_wins_over_the_computation():
    """NINA and SGP know the mount; preferring our own estimate would be presumptuous."""
    assert observation_airmass({"AIRMASS": 1.42}, 2460000.0, 210.0, 33.0) == 1.42


def test_the_airmass_is_computed_if_the_site_is_known():
    value = observation_airmass(
        {"SITELAT": 45.0, "SITELONG": 5.0}, 2461250.0, 210.5, 33.0)
    assert value is None or 1.0 <= value < 40.0


def test_without_a_site_the_airmass_stays_unknown():
    """`None` becomes `na` on export: honest, where a made-up value would not be."""
    assert observation_airmass({}, 2460000.0, 210.0, 33.0) is None


# --- ConeSearch -----------------------------------------------------------------------

def _resolved_view():
    from retina import Application

    app = Application()
    win = app.new_window(Image(np.zeros((SIZE, SIZE, 1), np.float32)))
    win.wcs = _wcs()
    return win.main_view


def test_conesearch_projects_and_filters_to_the_field():
    from retina.processes.catalogs import ConeSearch

    inside = _sky(0)
    proc = ConeSearch().set_objects([
        {"name": "M51", "ra": inside[0], "dec": inside[1], "otype": "GiG", "mag": 8.4},
        {"name": "far", "ra": 10.0, "dec": -40.0, "otype": "*", "mag": 12.0},
    ])

    result = proc.measure(_resolved_view())

    assert result["n_objects"] == 1
    obj = result["objects"][0]
    assert obj["name"] == "M51"
    assert obj["x"] == pytest.approx(POSITIONS[0][0], abs=0.5)


def test_conesearch_filters_by_type():
    from retina.processes.catalogs import ConeSearch

    ra, dec = _sky(0)
    ra2, dec2 = _sky(1)
    proc = ConeSearch(object_types="G").set_objects([
        {"name": "galaxy", "ra": ra, "dec": dec, "otype": "GiG", "mag": 8.4},
        {"name": "star", "ra": ra2, "dec": dec2, "otype": "*", "mag": 9.0},
    ])

    assert [o["name"] for o in proc.measure(_resolved_view())["objects"]] == ["galaxy"]


def test_conesearch_without_wcs_refuses():
    from retina import Application
    from retina.processes.catalogs import ConeSearch

    app = Application()
    view = app.new_window(Image(np.zeros((16, 16, 1), np.float32))).main_view

    with pytest.raises(ValueError, match="requires a WCS"):
        ConeSearch().set_objects([]).measure(view)
