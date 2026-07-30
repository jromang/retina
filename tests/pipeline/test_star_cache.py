"""Registration star cache (StarCache) — sep detection is paid for only once.

Two guarantees, each covering a possible regression: the alignment result is identical bit
for bit with and without the cache (the cached control points produce the same transform as
astroalign's internal detection); and a second pass over the same files detects nothing (the
detection counter stays at zero). To which is added the frozen key of the measurement cache:
generalizing it into FileDataCache must not invalidate existing v2 entries.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("astropy")
pytest.importorskip("astroalign")

from retina.io.fits import save_fits
from retina.model.image import Image
from retina.pipeline.file_cache import StarCache
from retina.pipeline.measure_cache import MeasureCache
from retina.processes import registration as reg


def _starfield(seed: int, dx: float = 0.0, dy: float = 0.0) -> np.ndarray:
    """Field of gaussian stars, shiftable — rich enough for astroalign (≥ 10)."""
    rng = np.random.default_rng(seed)
    h = w = 96
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    image = np.full((h, w), 0.02, dtype=np.float32)
    positions = rng.uniform(12, 84, size=(14, 2))
    for cx, cy in positions:
        image += 0.7 * np.exp(-(((x - cx - dx) ** 2 + (y - cy - dy) ** 2) / 3.0))
    image += rng.normal(0, 0.002, image.shape).astype(np.float32)
    return np.clip(image, 0, 1)[:, :, None].astype(np.float32)


@pytest.fixture
def files(tmp_path):
    ref = str(tmp_path / "ref.fits")
    src = str(tmp_path / "src.fits")
    save_fits(ref, Image(_starfield(3)))
    save_fits(src, Image(_starfield(3, dx=2.0, dy=-1.5)))
    return ref, src


def test_frozen_v2_key(tmp_path):
    """The key composition of the measurement cache must NEVER change silently: every byte
    of the JSON blob feeds the SHA-256, and a field added or renamed would invalidate the
    whole existing user cache without anything to say so."""
    path = str(tmp_path / "f.fits")
    save_fits(path, Image(np.zeros((4, 4, 1), dtype=np.float32)))
    import hashlib
    import json
    import os

    stat = os.stat(path)
    blob = json.dumps({
        "version": "2",
        "path": os.path.abspath(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "settings": {"fwhm": 3.0},
    }, sort_keys=True, ensure_ascii=False, default=repr)
    expected = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    assert MeasureCache.key(path, {"fwhm": 3.0}) == expected


def test_same_result_with_and_without_cache(files, tmp_path):
    from retina.processes.registration import StarAlignment

    ref, _src = files
    data = Image(_starfield(3, dx=2.0, dy=-1.5))

    without = StarAlignment(reference_path=ref).execute_on_image(data.copy())

    lum_ref = _starfield(3).mean(axis=2)
    lum_src = _starfield(3, dx=2.0, dy=-1.5).mean(axis=2)
    cached_proc = StarAlignment(reference_path=ref)
    cached_proc.reference_stars = reg.detect_alignment_stars(lum_ref)
    cached_proc.source_stars = reg.detect_alignment_stars(lum_src)
    assert len(cached_proc.reference_stars) >= 3
    cached = cached_proc.execute_on_image(data.copy())

    np.testing.assert_array_equal(cached.data, without.data)


def test_the_runner_detects_only_once(files, tmp_path, monkeypatch):
    """Two runs of the step: the second one is served entirely from the cache (zero sep)."""
    from retina.pipeline.runner import RunReport, _Runner

    ref, src = files
    cache_root = tmp_path / "star-cache"
    monkeypatch.setattr(
        "retina.pipeline.file_cache.config_path", lambda name: cache_root / name
    )

    count = {"n": 0}
    original = reg.detect_alignment_stars

    def counter(lum):
        count["n"] += 1
        return original(lum)

    monkeypatch.setattr(reg, "detect_alignment_stars", counter)

    def run_once(output: str) -> None:
        from retina.pipeline.plan import PlanStep
        from retina.process.container import ProcessContainer
        from retina.processes.registration import StarAlignment

        recipe = ProcessContainer()
        recipe.add(StarAlignment(reference_path=ref))
        step = PlanStep(id="reg", label="reg", kind="per_frame", recipe=recipe,
                        inputs=[src], outputs=[str(tmp_path / output)])
        runner = _Runner.__new__(_Runner)
        runner.failed = set()
        runner.report = RunReport(output_dir=str(tmp_path))
        from retina.process.progress import ProgressMonitor

        runner._run_per_frame(step, ProgressMonitor())

    run_once("out1.fits")
    first = count["n"]
    assert first == 2  # reference + source

    run_once("out2.fits")
    assert count["n"] == first  # everything came from the cache

    repo = StarCache(root=cache_root / "measure-cache")
    assert len(repo) == 2
