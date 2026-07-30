"""Survey reference (hips2fits) — cache, guard rails, and the process that puts it in a window.

**No test touches the network**: `hips._query` is the only point that talks to the CDS, and it
is the one we divert; the process itself has `set_reference` for the same reason that
`FindingChart` has `set_objects`.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image, hips
from retina.processes.gradient import SurveyReference


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """A test's HiPS cache must not outlive the test — nor pollute the machine."""
    monkeypatch.setenv("RETINA_CACHE_DIR", str(tmp_path / "cache"))


def _wcs(h=64, w=96, ra=10.0, dec=20.0):
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [w / 2, h / 2]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [ra, dec]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.pixel_shape = (w, h)
    return wcs


def _fake_sky(shape):
    ys, xs = np.mgrid[0 : shape[0], 0 : shape[1]].astype(np.float64)
    return 100.0 + 40.0 * np.exp(-((xs - shape[1] / 2) ** 2 + (ys - shape[0] / 2) ** 2) / 200.0)


class _Counter:
    """Diverts the request and counts the calls — that is how the cache gets proven."""

    def __init__(self, factory=None):
        self.calls = 0
        self._factory = factory or _fake_sky

    def __call__(self, hips_id, wcs):
        self.calls += 1
        shape = (wcs.pixel_shape[1], wcs.pixel_shape[0])
        return self._factory(shape)


# --- survey resolution and reduced grid --------------------------------------------------

def test_slug_to_hips_identifier():
    assert hips.hips_id_for("dss2-red") == "CDS/P/DSS2/red"
    assert hips.hips_id_for("custom", "CDS/P/AllWISE/W1") == "CDS/P/AllWISE/W1"


def test_custom_without_an_identifier_raises():
    with pytest.raises(ValueError):
        hips.hips_id_for("custom")
    with pytest.raises(ValueError):
        hips.hips_id_for("unknown-survey")


def test_the_reduced_grid_covers_the_same_footprint():
    """Downsampling must not move the field: that is all that is required of it."""
    large = _wcs(2000, 3000)
    small, shape = hips.reduced_wcs(large, (2000, 3000), max_size=256)

    assert max(shape) <= 256
    assert small.pixel_shape == (shape[1], shape[0])
    # opposite corners of the two grids point at the same place in the sky
    for (xg, yg), (xp, yp) in (((0, 0), (0, 0)), ((2999, 1999), (shape[1] - 1, shape[0] - 1))):
        a = large.pixel_to_world(xg, yg)
        b = small.pixel_to_world(xp, yp)
        assert a.separation(b).arcsec < 30.0


def test_without_reduction_the_grid_is_unchanged():
    large = _wcs(64, 96)
    _small, shape = hips.reduced_wcs(large, (64, 96), max_size=0)
    assert shape == (64, 96)


# --- fetch: normalisation, cache, guard rails --------------------------------------------

def test_fetch_normalises_and_returns_the_reduced_grid(monkeypatch):
    monkeypatch.setattr(hips, "_query", _Counter())

    plane, ref_wcs = hips.fetch(_wcs(400, 600), (400, 600), "dss2-red", max_size=128)

    assert plane.dtype == np.float32
    assert max(plane.shape) <= 128
    assert plane.min() >= 0.0 and plane.max() <= 1.0
    assert ref_wcs.pixel_shape == (plane.shape[1], plane.shape[0])


def test_the_second_request_does_not_go_through_the_network_again(monkeypatch):
    counter = _Counter()
    monkeypatch.setattr(hips, "_query", counter)
    wcs = _wcs(200, 200)

    a, _ = hips.fetch(wcs, (200, 200), "dss2-red", max_size=64)
    b, _ = hips.fetch(wcs, (200, 200), "dss2-red", max_size=64)

    assert counter.calls == 1
    np.testing.assert_array_equal(a, b)


def test_changing_survey_field_or_size_changes_the_key(monkeypatch):
    counter = _Counter()
    monkeypatch.setattr(hips, "_query", counter)

    hips.fetch(_wcs(200, 200), (200, 200), "dss2-red", max_size=64)
    hips.fetch(_wcs(200, 200), (200, 200), "dss2-blue", max_size=64)
    hips.fetch(_wcs(200, 200, ra=180.0), (200, 200), "dss2-red", max_size=64)
    hips.fetch(_wcs(200, 200), (200, 200), "dss2-red", max_size=32)

    assert counter.calls == 4


def test_use_cache_false_always_asks_again(monkeypatch):
    counter = _Counter()
    monkeypatch.setattr(hips, "_query", counter)
    wcs = _wcs(100, 100)

    hips.fetch(wcs, (100, 100), "dss2-red", max_size=64, use_cache=False)
    hips.fetch(wcs, (100, 100), "dss2-red", max_size=64, use_cache=False)

    assert counter.calls == 2


def test_a_field_outside_the_coverage_is_refused_explicitly(monkeypatch):
    """PanSTARRS does not reach below −30°: a reference full of holes would invent a sky."""

    def holed(shape):
        plane = _fake_sky(shape)
        plane[: int(0.8 * shape[0])] = np.nan
        return plane

    monkeypatch.setattr(hips, "_query", _Counter(holed))

    with pytest.raises(ValueError, match="covers only"):
        hips.fetch(_wcs(100, 100), (100, 100), "panstarrs-g", max_size=64)


def test_a_few_holes_are_filled_rather_than_dug(monkeypatch):
    """A zero inside a hole would dig a crater that the correction would take for sky."""

    def slightly_holed(shape):
        plane = _fake_sky(shape)
        plane[:2, :2] = np.nan
        return plane

    monkeypatch.setattr(hips, "_query", _Counter(slightly_holed))

    plane, _ = hips.fetch(_wcs(100, 100), (100, 100), "dss2-red", max_size=64)

    assert np.isfinite(plane).all()
    assert plane[0, 0] == pytest.approx(float(np.median(plane)), abs=0.2)


def test_the_cache_carries_its_provenance(monkeypatch):
    """A cache file must be able to say where it comes from, otherwise it is an anonymous
    array."""
    from astropy.io import fits

    monkeypatch.setattr(hips, "_query", _Counter())
    wcs = _wcs(100, 100)
    hips.fetch(wcs, (100, 100), "dss2-red", max_size=64)

    small, shape = hips.reduced_wcs(wcs, (100, 100), 64)
    path = hips.cache_file("dss2-red", "CDS/P/DSS2/red", small, shape)
    assert path.exists()
    with fits.open(path) as hdul:
        assert hdul[0].header["HIPSID"] == "CDS/P/DSS2/red"
        assert hdul[0].header["HIPSSVC"] == "CDS hips2fits"
    assert not path.with_suffix(".part").exists()  # nothing truncated is left behind


def test_a_failing_cache_write_does_not_fail_the_request(monkeypatch):
    monkeypatch.setattr(hips, "_query", _Counter())
    monkeypatch.setattr(hips, "_write_cache", lambda *a, **k: (_ for _ in ()).throw(OSError()))

    with pytest.raises(OSError):
        hips.fetch(_wcs(100, 100), (100, 100), "dss2-red", max_size=64)


# --- the process ---------------------------------------------------------------------------

def test_without_an_astrometric_solution_the_process_refuses():
    app = Application()
    app.new_window(Image(np.zeros((64, 96, 1), np.float32)))

    with pytest.raises(ValueError, match="astrometric solution"):
        SurveyReference().execute_global(app)


def test_the_process_creates_a_solved_and_traceable_window():
    app = Application()
    win = app.new_window(Image(np.zeros((64, 96, 1), np.float32)), window_id="M31")
    win.wcs = _wcs(64, 96)
    plane = _fake_sky((32, 48)).astype(np.float32)

    assert SurveyReference(survey="dss2-red", max_size=48).set_reference(plane).execute_global(app)

    reference = app.windows[-1]
    assert reference.id == "M31_dss2-red"
    assert reference.has_astrometric_solution
    assert reference.keywords["HIPSSURV"] == "dss2-red"
    # same field as the source: this is what makes the two views superimposable
    center_source = win.wcs.pixel_to_world(48.0, 32.0)
    center_ref = reference.wcs.pixel_to_world(24.0, 16.0)
    assert center_source.separation(center_ref).arcsec < 30.0


def test_an_unknown_source_window_raises():
    app = Application()
    with pytest.raises(ValueError, match="Window not found"):
        SurveyReference(view_id="not_here").execute_global(app)


def test_the_process_feeds_the_gradient_correction(monkeypatch):
    """The complete gesture, as it is done from the console — and without the network."""
    from retina.processes.gradient import MultiscaleGradientCorrection

    monkeypatch.setattr(hips, "_query", _Counter())
    app = Application()
    ys, xs = np.mgrid[0:128, 0:128].astype(np.float32)
    observed = 0.05 + 0.15 * (xs / 127.0) + 0.2 * np.exp(-((xs - 64) ** 2 + (ys - 64) ** 2) / 800)
    win = app.new_window(Image(observed[:, :, None]), window_id="target")
    win.wcs = _wcs(128, 128)

    SurveyReference(max_size=64).execute_global(app)
    reference = app.windows[-1]
    ok = MultiscaleGradientCorrection(scale=5, reference=reference.main_view.id).execute_on(
        win.main_view
    )

    assert ok
    assert win.main_view.history_index == 1  # one history entry, replayable
