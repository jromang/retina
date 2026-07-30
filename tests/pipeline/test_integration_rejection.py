"""Adaptive rejection and band-wise integration.

Two deferred points. The first decides the quality of the stacking on small frame counts,
the second decides feasibility at all on large sensors.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.io.fits import save_fits
from retina.io.lazy import open_lazy
from retina.model.image import Image
from retina.process.registry import get
from retina.processes.integration import choose_rejection


def write_frames(tmp_path, arrays) -> list[str]:
    paths = []
    for i, t in enumerate(arrays):
        p = str(tmp_path / f"f{i:03d}.fits")
        save_fits(p, Image(np.asarray(t, dtype=np.float32)))
        paths.append(p)
    return paths


def noisy_frames(n, value=0.5, shape=(8, 8, 1), sigma=0.01, seed=0):
    rng = np.random.default_rng(seed)
    return [np.clip(value + rng.normal(0, sigma, shape), 0, 1).astype(np.float32)
            for _ in range(n)]


# --- automatic choice ------------------------------------------------------------------

def test_auto_mode_follows_the_frame_count():
    assert choose_rejection(2) == "none"          # nothing to estimate
    assert choose_rejection(4) == "percentile"
    assert choose_rejection(10) == "winsorized"
    assert choose_rejection(30) == "linear_fit"


def test_a_master_stays_winsorized_whatever_the_frame_count():
    """Plenty of fixed structure: rejection must not take it for outlier signal."""
    assert choose_rejection(40, kind="master") == "winsorized"


def test_the_process_resolves_auto_for_its_frame_count(tmp_path):
    paths = write_frames(tmp_path, noisy_frames(4))
    process = get("Integration")(frames=paths)

    assert process.rejection == "auto"
    assert process.effective_rejection(4) == "percentile"
    assert process.effective_rejection(30) == "linear_fit"


def test_an_explicit_mode_is_not_overridden(tmp_path):
    process = get("Integration")(frames=write_frames(tmp_path, noisy_frames(4)), rejection="sigma")

    assert process.effective_rejection(4) == "sigma"


# --- effectiveness of each mode ---------------------------------------------------------

@pytest.mark.parametrize("mode,n", [("percentile", 5), ("winsorized", 10),
                                    ("linear_fit", 20), ("sigma", 20)])
def test_every_mode_rejects_a_cosmic_ray(tmp_path, mode, n):
    frames = noisy_frames(n, seed=3)
    frames[0][4, 4, 0] = 1.0  # cosmic ray on a single sub
    out = get("Integration")(frames=write_frames(tmp_path, frames), rejection=mode).combine()

    assert abs(float(out[4, 4, 0]) - 0.5) < 0.03, mode


def test_percentile_saves_a_four_frame_stack(tmp_path):
    """This is where sigma rejection fails: four samples say nothing about a dispersion."""
    frames = noisy_frames(4, seed=5)
    frames[0][4, 4, 0] = 1.0
    paths = write_frames(tmp_path, frames)

    percentile = get("Integration")(frames=paths, rejection="percentile").combine()
    without = get("Integration")(frames=paths, rejection="none").combine()

    assert abs(float(percentile[4, 4, 0]) - 0.5) < abs(float(without[4, 4, 0]) - 0.5)


def test_the_linear_fit_tolerates_an_illumination_drift(tmp_path):
    """A transparency drift between subs is a slope, not dispersion."""
    rng = np.random.default_rng(7)
    frames = [np.full((8, 8, 1), 0.30 + 0.01 * i, dtype=np.float32)
              + rng.normal(0, 0.002, (8, 8, 1)).astype(np.float32) for i in range(20)]
    paths = write_frames(tmp_path, frames)

    linear = get("Integration")(frames=paths, rejection="linear_fit")
    rejected = linear._reject(np.stack([np.asarray(f) for f in frames]), "linear_fit")

    # the drift is absorbed: almost nothing is discarded
    assert rejected.mean() < 0.05


def test_no_mode_rejects_a_constant_stack(tmp_path):
    """Zero dispersion: dividing by the scale must not discard healthy pixels."""
    frames = [np.full((8, 8, 1), 0.4, dtype=np.float32) for _ in range(10)]
    paths = write_frames(tmp_path, frames)

    for mode in ("sigma", "winsorized", "percentile", "linear_fit"):
        out = get("Integration")(frames=paths, rejection=mode).combine()
        assert np.allclose(out, 0.4, atol=1e-6), mode


def test_rejection_does_not_apply_below_three_frames(tmp_path):
    paths = write_frames(tmp_path, noisy_frames(2))
    process = get("Integration")(frames=paths)

    assert process.effective_rejection(2) == "none"
    assert np.allclose(process.combine(), np.mean([
        np.asarray(open_lazy(c).band(0, 8)) for c in paths], axis=0), atol=1e-6)


# --- band-wise integration ----------------------------------------------------------------

def test_tiling_gives_exactly_the_same_result(tmp_path):
    """Rejection works pixel by pixel: cutting into bands cannot change anything."""
    frames = noisy_frames(9, shape=(32, 24, 1), seed=11)
    frames[2][10, 5, 0] = 1.0
    paths = write_frames(tmp_path, frames)

    whole = get("Integration")(frames=paths, max_memory_mb=4096.0)
    tile = get("Integration")(frames=paths, max_memory_mb=0.002)

    # the split is real, otherwise the test would prove nothing
    assert whole._band_rows(32, 24, 1, 9) == 32
    assert tile._band_rows(32, 24, 1, 9) < 32

    assert np.array_equal(whole.combine(), tile.combine())


def test_tiling_holds_in_color_too(tmp_path):
    frames = noisy_frames(6, shape=(16, 12, 3), seed=13)
    paths = write_frames(tmp_path, frames)

    whole = get("Integration")(frames=paths, max_memory_mb=4096.0).combine()
    tile = get("Integration")(frames=paths, max_memory_mb=0.002)

    assert tile._band_rows(16, 12, 3, 6) < 16
    assert np.array_equal(whole, tile.combine())


def test_tiling_respects_the_weights(tmp_path):
    paths = write_frames(tmp_path, [np.full((16, 8, 1), 0.2, dtype=np.float32),
                                    np.full((16, 8, 1), 0.4, dtype=np.float32)])
    process = get("Integration")(frames=paths, weights=[3.0, 1.0], rejection="none",
                                 max_memory_mb=0.0001)

    assert process._band_rows(16, 8, 1, 2) < 16
    assert process.combine() == pytest.approx(0.25, abs=1e-6)


def test_the_band_height_fits_in_the_budget():
    tight = get("Integration")(frames=["a"], max_memory_mb=1.0)
    # 100 frames 1000 px wide in mono: 400 kB per row → 2 rows in 1 MB
    assert tight._band_rows(2000, 1000, 1, 100) == 2
    # absurd budget: at least one row, never zero
    assert tight._band_rows(2000, 10000, 3, 500) == 1

    large = get("Integration")(frames=["a"], max_memory_mb=512.0)
    # 4 frames of 1000 px: 16 kB per row, everything fits at once
    assert large._band_rows(2000, 1000, 1, 4) == 2000


def test_heterogeneous_geometries_are_rejected(tmp_path):
    paths = write_frames(tmp_path, [np.zeros((8, 8, 1), np.float32),
                                    np.zeros((16, 8, 1), np.float32)])

    with pytest.raises(ValueError, match="geometries"):
        get("Integration")(frames=paths).combine()


# --- lazy reading --------------------------------------------------------------------------

def test_the_band_reader_returns_the_same_pixels(tmp_path):
    from retina.io import load_image_array

    data = np.random.default_rng(2).uniform(0, 1, (20, 14, 3)).astype(np.float32)
    path = str(tmp_path / "img.fits")
    save_fits(path, Image(data))

    complete = load_image_array(path)
    with open_lazy(path) as reader:
        assert reader.shape == (20, 14, 3)
        chunks = [reader.band(y, min(y + 7, 20)) for y in range(0, 20, 7)]

    assert np.allclose(np.concatenate(chunks, axis=0), complete, atol=1e-6)


def test_the_reader_normalizes_like_a_full_load(tmp_path):
    """Otherwise a band-wise integration would not give the same result as a single block."""
    from astropy.io import fits
    from retina.io import load_image_array

    path = str(tmp_path / "whole.fits")
    fits.PrimaryHDU(np.arange(64, dtype=np.uint16).reshape(8, 8)).writeto(path)

    with open_lazy(path) as reader:
        assert np.allclose(reader.band(0, 8), load_image_array(path), atol=1e-9)


def test_the_reader_accepts_formats_without_partial_reads(tmp_path):
    """Same contract, no saving at all: better said out loud than left to be assumed."""
    from retina.io.raster import save_raster

    path = str(tmp_path / "img.png")
    save_raster(path, Image(np.full((12, 10, 3), 0.5, dtype=np.float32)))

    with open_lazy(path) as reader:
        assert reader.shape == (12, 10, 3)
        assert reader.band(4, 8).shape == (4, 10, 3)


# --- tolerance to unreadable files -------------------------------------------------------

def test_one_unreadable_frame_does_not_cancel_the_others(tmp_path):
    """One truncated file among thirty must not take the other twenty-nine down with it."""
    paths = write_frames(tmp_path, [np.full((8, 8, 1), v, np.float32) for v in (0.2, 0.4, 0.6)])
    (tmp_path / "broken.fits").write_bytes(b"not FITS")
    paths.insert(1, str(tmp_path / "broken.fits"))

    process = get("Integration")(frames=paths, rejection="none")
    out = process.combine()

    assert out == pytest.approx(0.4, abs=1e-5)  # mean of the three readable ones
    assert [c for c, _ in process.skipped] == [str(tmp_path / "broken.fits")]


def test_the_weights_follow_the_readable_frames(tmp_path):
    """Otherwise they would be off by one and weight the wrong frames."""
    paths = write_frames(tmp_path, [np.full((8, 8, 1), v, np.float32) for v in (0.2, 0.4)])
    (tmp_path / "broken.fits").write_bytes(b"not FITS")
    paths.insert(1, str(tmp_path / "broken.fits"))

    out = get("Integration")(frames=paths, weights=[3.0, 99.0, 1.0],
                             rejection="none").combine()

    assert out == pytest.approx(0.25, abs=1e-5)  # 3·0.2 + 1·0.4, the weight of 99 discarded


def test_all_unreadable_frames_raise(tmp_path):
    (tmp_path / "a.fits").write_bytes(b"x")
    (tmp_path / "b.fits").write_bytes(b"y")

    with pytest.raises(ValueError, match="no readable frames"):
        get("Integration")(frames=[str(tmp_path / "a.fits"),
                                   str(tmp_path / "b.fits")]).combine()
