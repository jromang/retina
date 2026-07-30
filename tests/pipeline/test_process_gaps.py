"""The process gaps the pipeline demanded.

Four missing capabilities made an automated pre-processing run impossible or wrong:
weighting at integration, the per-file reference in normalization, dark scaling and the
pedestal. These tests pin down their contract.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.io.fits import save_fits
from retina.model.image import Image
from retina.process.registry import all_processes, get


def write_fits(path, value, size=(8, 8, 1)):
    """Write a constant FITS and return its path."""
    save_fits(str(path), Image(np.full(size, value, dtype=np.float32)))
    return str(path)


# --- Integration: per-frame weights --------------------------------------------------

def frames_of(tmp_path, values):
    return [write_fits(tmp_path / f"f{i}.fits", v) for i, v in enumerate(values)]


def test_without_weights_integration_stays_a_mean(tmp_path):
    paths = frames_of(tmp_path, [0.2, 0.4])
    out = get("Integration")(frames=paths, rejection="none").combine()

    assert out == pytest.approx(0.3, abs=1e-5)


def test_the_weights_move_the_result(tmp_path):
    """A frame scored three times better weighs three times more."""
    paths = frames_of(tmp_path, [0.2, 0.4])
    out = get("Integration")(frames=paths, weights=[3.0, 1.0], rejection="none").combine()

    assert out == pytest.approx(0.25, abs=1e-5)


def test_the_weights_do_not_need_to_be_normalized(tmp_path):
    paths = frames_of(tmp_path, [0.2, 0.4])
    a = get("Integration")(frames=paths, weights=[3.0, 1.0], rejection="none").combine()
    b = get("Integration")(frames=paths, weights=[0.75, 0.25], rejection="none").combine()

    assert a == pytest.approx(b, abs=1e-6)


def test_a_zero_weight_excludes_the_frame_from_the_mean(tmp_path):
    paths = frames_of(tmp_path, [0.2, 0.4])
    out = get("Integration")(frames=paths, weights=[0.0, 1.0], rejection="none").combine()

    assert out == pytest.approx(0.4, abs=1e-5)


def test_the_weights_do_not_replace_rejection(tmp_path):
    """A cosmic ray must be discarded, not merely attenuated."""
    rng = np.random.default_rng(4)
    frames = [np.clip(0.5 + rng.normal(0, 0.01, (8, 8, 1)), 0, 1).astype(np.float32)
              for _ in range(7)]
    frames[0][4, 4, 0] = 1.0
    paths = []
    for i, f in enumerate(frames):
        p = str(tmp_path / f"c{i}.fits")
        save_fits(p, Image(f))
        paths.append(p)

    weights = [5.0] + [1.0] * 6  # the polluted frame is also the best-scored one
    out = get("Integration")(frames=paths, weights=weights, rejection="sigma").combine()

    assert abs(out[4, 4, 0] - 0.5) < 0.05


def test_an_inconsistent_number_of_weights_raises(tmp_path):
    paths = frames_of(tmp_path, [0.2, 0.4])
    with pytest.raises(ValueError, match="weights"):
        get("Integration")(frames=paths, weights=[1.0]).combine()


def test_all_zero_weights_raise(tmp_path):
    paths = frames_of(tmp_path, [0.2, 0.4])
    with pytest.raises(ValueError, match="zero"):
        get("Integration")(frames=paths, weights=[0.0, 0.0]).combine()


# --- ImageCalibration: dark scaling and pedestal -------------------------------------

def test_the_dark_is_scaled(tmp_path):
    """light − bias − k·dark_current: the setup with a dark of a different exposure."""
    bias = write_fits(tmp_path / "bias.fits", 0.10)
    current = write_fits(tmp_path / "darkc.fits", 0.20)  # dark already bias-subtracted
    light = Image(np.full((8, 8, 1), 0.55, dtype=np.float32))

    out = get("ImageCalibration")(master_bias=bias, master_dark=current, dark_scale=0.5,
                                  pedestal_mode="none").execute_on_image(light)

    assert np.allclose(out.data, 0.55 - 0.10 - 0.5 * 0.20, atol=1e-5)


def test_the_default_scale_changes_nothing(tmp_path):
    """Backward compatibility: dark_scale=1 leaves the historical formula intact."""
    dark = write_fits(tmp_path / "dark.fits", 0.15)
    light = Image(np.full((8, 8, 1), 0.5, dtype=np.float32))

    out = get("ImageCalibration")(master_dark=dark, pedestal_mode="none").execute_on_image(light)

    assert np.allclose(out.data, 0.35, atol=1e-5)


def test_the_auto_pedestal_lifts_the_negative_background(tmp_path):
    """Without a pedestal, half the background noise would be clipped to zero."""
    rng = np.random.default_rng(1)
    dark = write_fits(tmp_path / "dark.fits", 0.30, size=(64, 64, 1))
    raw_data = 0.30 + rng.normal(0.0, 0.02, (64, 64, 1)).astype(np.float32)

    without = get("ImageCalibration")(master_dark=dark, pedestal_mode="none")
    with_pedestal = get("ImageCalibration")(master_dark=dark, pedestal_mode="auto")

    clipped = without.execute_on_image(Image(raw_data)).data
    lifted = with_pedestal.execute_on_image(Image(raw_data)).data

    assert (clipped == 0.0).mean() > 0.4          # half the noise is lost
    assert (lifted == 0.0).mean() < 1e-3          # almost nothing is clipped any more
    assert lifted.std() > clipped.std()           # the background dispersion is preserved


def test_the_manual_pedestal_is_an_addition(tmp_path):
    dark = write_fits(tmp_path / "dark.fits", 0.30)
    light = Image(np.full((8, 8, 1), 0.40, dtype=np.float32))

    out = get("ImageCalibration")(master_dark=dark, pedestal_mode="manual",
                                  pedestal=0.05).execute_on_image(light)

    assert np.allclose(out.data, 0.15, atol=1e-5)


def test_the_auto_pedestal_does_not_move_a_positive_image(tmp_path):
    bias = write_fits(tmp_path / "bias.fits", 0.1)
    light = Image(np.full((8, 8, 1), 0.5, dtype=np.float32))

    out = get("ImageCalibration")(master_bias=bias).execute_on_image(light)

    assert np.allclose(out.data, 0.4, atol=1e-5)


# --- LocalNormalization: per-file reference ------------------------------------------

def test_normalization_accepts_a_file_reference(tmp_path):
    rng = np.random.default_rng(2)
    ref = (0.3 + rng.normal(0, 0.05, (32, 32, 1))).astype(np.float32)
    path = str(tmp_path / "ref.fits")
    save_fits(path, Image(np.clip(ref, 0, 1)))

    target = Image(np.clip(ref * 0.5 + 0.2, 0, 1).astype(np.float32))
    out = get("LocalNormalization")(reference_path=path, scale=8.0).execute_on_image(target)

    # the target's background is brought back onto the reference's
    assert abs(float(out.data.mean()) - float(ref.mean())) < 0.02


def test_a_missing_reference_raises_instead_of_doing_nothing():
    """A silent no-op would produce an unnormalized integration, undetectable."""
    target = Image(np.full((8, 8, 1), 0.3, dtype=np.float32))

    with pytest.raises(ValueError, match="Reference not found"):
        get("LocalNormalization")(reference="missing_view").execute_on_image(target)


def test_without_a_reference_normalization_stays_a_no_op():
    target = Image(np.full((8, 8, 1), 0.3, dtype=np.float32))
    out = get("LocalNormalization")().execute_on_image(target)

    assert np.allclose(out.data, 0.3)


# --- eligibility for the real-time preview -------------------------------------------

def test_no_global_process_is_a_preview_candidate():
    offenders = [n for n, c in all_processes().items() if c.is_global and c.realtime_capable()]

    assert offenders == []


def test_the_slow_processes_are_excluded_from_the_preview():
    for name in ("PlateSolve", "StarAlignment", "ImageCalibration", "LocalNormalization",
                "Debayer", "StarRemoval", "CatalogAnnotation"):
        assert not get(name).realtime_capable(), name


def test_ordinary_processes_stay_candidates():
    for name in ("GaussianConvolution", "HistogramTransformation", "CurvesTransformation"):
        assert get(name).realtime_capable(), name


def test_the_preview_explicitly_refuses_the_excluded_processes():
    image = Image(np.zeros((8, 8, 1), dtype=np.float32))

    with pytest.raises(RuntimeError, match="real-time preview"):
        get("StarAlignment")(reference_id="x").execute_preview(image)


# --- guards revealed by a real dataset ------------------------------------------------

def test_a_blind_flat_does_not_blow_up_the_image(tmp_path):
    """A flat pixel at zero does not call for an infinite correction: it saw nothing.

    Real case: the overscan area of a CCD is not illuminated, hence zero in the flat.
    Dividing by it multiplied the noise by a million.
    """
    flat = np.full((16, 16, 1), 0.6, dtype=np.float32)
    flat[:, :3, :] = 0.0          # overscan columns, never illuminated
    flat[8, 8, 0] = 1e-6          # dead pixel
    path = write_fits(tmp_path / "flat.fits", 0.0, size=(16, 16, 1))
    save_fits(path, Image(flat))

    out = get("ImageCalibration")(master_flat=path,
                                  pedestal_mode="none").execute_on_image(
        Image(np.full((16, 16, 1), 0.3, dtype=np.float32))).data

    assert np.isfinite(out).all()
    assert out.max() <= 1.0
    # blind pixels are left as they are, not amplified
    assert out[0, 0, 0] == pytest.approx(0.3, abs=1e-6)
    assert out[8, 8, 0] == pytest.approx(0.3, abs=1e-6)


def test_a_valid_flat_is_indeed_applied(tmp_path):
    """The guard must not prevent the correction where the flat is good."""
    flat = np.full((16, 16, 1), 0.5, dtype=np.float32)
    flat[:8] = 0.6  # 20 % apart between the two halves
    path = str(tmp_path / "flat.fits")
    save_fits(path, Image(flat))

    out = get("ImageCalibration")(master_flat=path,
                                  pedestal_mode="none").execute_on_image(
        Image(np.full((16, 16, 1), 0.5, dtype=np.float32))).data

    assert out[:8].mean() < out[8:].mean()  # the brighter half is brought further down


def test_the_pedestal_ignores_pathological_pixels():
    """Distorting 100 % of the image to save 0.01 % of the pixels is never the right call."""
    rng = np.random.default_rng(0)
    data = rng.normal(0.0, 0.001, (200, 200, 1)).astype(np.float32)
    data[0, 0, 0] = -500.0  # a single dead column is enough to shift everything

    process = get("ImageCalibration")(pedestal_mode="auto")
    pedestal = process._auto_pedestal(data)

    assert pedestal < 0.01            # on the order of the noise, not of the aberration
    assert pedestal > 0.0             # but it does lift the background


def test_the_pedestal_stays_useful_on_a_healthy_image():
    rng = np.random.default_rng(1)
    data = rng.normal(0.0, 0.002, (200, 200, 1)).astype(np.float32)

    lifted = get("ImageCalibration")(pedestal_mode="auto")._auto_pedestal(data)

    assert lifted == pytest.approx(0.002 * 3.7, rel=0.4)  # ≈ the quantile at 1e-4
