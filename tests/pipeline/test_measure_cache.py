"""Persistent measurement cache — adding a night does not remeasure the previous ones.

The run cache works per **step**: the list of frames enters its fingerprint, so adding twenty
frames to a project had a hundred and twenty of them measured again. This one works per
**file**, and that is its entire purpose.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("astropy")

from retina.io.fits import save_fits
from retina.model.image import Image
from retina.pipeline.measure_cache import MeasureCache
from retina.processes.subframe import SubframeSelector


@pytest.fixture
def repo(tmp_path) -> MeasureCache:
    return MeasureCache(root=tmp_path / "cache")


def frame(tmp_path, name: str, level: float = 0.1) -> str:
    path = str(tmp_path / name)
    save_fits(path, Image(np.full((16, 16, 1), level, dtype=np.float32)))
    return path


# --- key ------------------------------------------------------------------------------

def test_the_key_tells_two_detection_settings_apart(tmp_path):
    a = frame(tmp_path, "a.fits")

    assert MeasureCache.key(a, {"fwhm": 3.0}) != MeasureCache.key(a, {"fwhm": 4.0})


def test_the_key_follows_the_content_of_the_file(tmp_path):
    """Size and date: the same trade-off as the run cache, and the same remedy."""
    a = frame(tmp_path, "a.fits", 0.1)
    before = MeasureCache.key(a, {})
    save_fits(a, Image(np.full((32, 32, 1), 0.2, dtype=np.float32)))

    assert MeasureCache.key(a, {}) != before


def test_two_identical_files_have_distinct_keys(tmp_path):
    """The key carries the path: two copies must not share an entry."""
    a, b = frame(tmp_path, "a.fits"), frame(tmp_path, "b.fits")

    assert MeasureCache.key(a, {}) != MeasureCache.key(b, {})


def test_a_missing_file_is_not_read_back(repo):
    assert repo.get("/nowhere/at_all.fits", {}) is None


# --- round trip -----------------------------------------------------------------------

def test_a_stored_measurement_is_read_back(tmp_path, repo):
    a = frame(tmp_path, "a.fits")
    repo.put(a, {"fwhm": 3.0}, {"stars": 42, "fwhm": 3.3})

    assert repo.get(a, {"fwhm": 3.0}) == {"stars": 42, "fwhm": 3.3}
    assert repo.get(a, {"fwhm": 9.0}) is None


def test_the_returned_measurement_is_a_copy(tmp_path, repo):
    """The caller adds `frame` to it, then the batch-derived quantities... without ever
    polluting the cached entry."""
    a = frame(tmp_path, "a.fits")
    repo.put(a, {}, {"stars": 42})

    reread = repo.get(a, {})
    reread["approved"] = False

    assert "approved" not in repo.get(a, {})


def test_the_cache_outlives_the_session(tmp_path):
    a = frame(tmp_path, "a.fits")
    first = MeasureCache(root=tmp_path / "cache")
    first.put(a, {}, {"stars": 7})
    first.flush()

    assert MeasureCache(root=tmp_path / "cache").get(a, {}) == {"stars": 7}


def test_an_entry_that_is_too_old_is_forgotten(tmp_path):
    a = frame(tmp_path, "a.fits")
    written = MeasureCache(root=tmp_path / "cache")
    written.put(a, {}, {"stars": 7})
    written.flush()

    stale = MeasureCache(root=tmp_path / "cache", max_age_days=0.0)

    assert stale.get(a, {}) is None
    assert len(stale) == 0


def test_clearing_the_cache_clears_it_on_disk_too(tmp_path):
    a = frame(tmp_path, "a.fits")
    repo = MeasureCache(root=tmp_path / "cache")
    repo.put(a, {}, {"stars": 7})
    repo.flush()

    repo.clear()

    assert MeasureCache(root=tmp_path / "cache").get(a, {}) is None


def test_a_corrupted_cache_file_is_ignored(tmp_path):
    """An unreadable cache rebuilds itself; it must not break a pre-processing run."""
    root = tmp_path / "cache"
    root.mkdir()
    (root / "measures.json").write_text("{ not json at all", encoding="utf-8")

    assert len(MeasureCache(root=root)) == 0


# --- what the cache actually saves ----------------------------------------------------

def _count_the_measurements(monkeypatch) -> list[str]:
    """Instruments `measure_array`: we count what is really computed."""
    views: list[str] = []
    real = SubframeSelector.measure_array

    def count(self, data):
        views.append("measurement")
        return real(self, data)

    monkeypatch.setattr(SubframeSelector, "measure_array", count)
    return views


def test_adding_a_night_does_not_remeasure_the_previous_ones(tmp_path, monkeypatch):
    """The test that justifies the whole module.

    We measure three frames, add two more, and measure again: only the two new ones should
    cost a star detection.
    """
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path / "config"))
    first_night = [frame(tmp_path, f"n1_{i}.fits", 0.1 + 0.01 * i) for i in range(3)]

    views = _count_the_measurements(monkeypatch)
    SubframeSelector(frames=first_night).measure_raw()
    assert len(views) == 3

    views.clear()
    added = [frame(tmp_path, f"n2_{i}.fits", 0.2 + 0.01 * i) for i in range(2)]
    SubframeSelector(frames=first_night + added).measure_raw()

    assert len(views) == 2, "the first three should have come from the cache"


def test_changing_a_detection_setting_remeasures_everything(tmp_path, monkeypatch):
    """The flip side: the key carries the settings, so a different measurement is redone."""
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path / "config"))
    frames = [frame(tmp_path, f"a{i}.fits", 0.1 + 0.01 * i) for i in range(3)]
    SubframeSelector(frames=frames).measure_raw()

    views = _count_the_measurements(monkeypatch)
    SubframeSelector(frames=frames, fwhm=5.0).measure_raw()

    assert len(views) == 3


def test_the_criteria_do_not_trigger_a_remeasure(tmp_path, monkeypatch):
    """A reject or an expression does not touch the measurement — so not the cache key."""
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path / "config"))
    frames = [frame(tmp_path, f"a{i}.fits", 0.1 + 0.01 * i) for i in range(3)]
    SubframeSelector(frames=frames).measure_raw()

    views = _count_the_measurements(monkeypatch)
    SubframeSelector(frames=frames, approval="snr > 1", manual_rejects=[frames[0]]).measure_raw()

    assert views == []


def test_the_cache_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path / "config"))
    frames = [frame(tmp_path, "a.fits")]
    SubframeSelector(frames=frames).measure_raw()

    views = _count_the_measurements(monkeypatch)
    SubframeSelector(frames=frames, use_cache=False).measure_raw()

    assert len(views) == 1


def test_enabling_the_cache_does_not_change_the_step_fingerprint():
    """Otherwise flipping the checkbox would redo all the work it exists to avoid."""
    a = SubframeSelector(frames=["/a.fits"], use_cache=True).cache_values()
    b = SubframeSelector(frames=["/a.fits"], use_cache=False).cache_values()

    assert a == b


def test_the_cache_key_ignores_the_list_of_frames():
    """This is what makes the cache incremental: without it, adding one frame would change
    the key of every other."""
    one = SubframeSelector(frames=["/a.fits"]).detection_values()
    two = SubframeSelector(frames=["/a.fits", "/b.fits"]).detection_values()

    assert one == two
    assert "frames" not in one
