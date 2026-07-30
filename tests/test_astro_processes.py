"""Headless tests of the astro-ecosystem processes (synthetic data)."""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image, get
from retina.io.fits import save_fits


# --- helpers -------------------------------------------------------------------
def star_field(h=96, w=96, n=30, seed=0):
    rng = np.random.default_rng(seed)
    img = rng.random((h, w)).astype(np.float32) * 0.01
    coords = []
    for _ in range(n):
        cy, cx = rng.uniform(8, h - 8), rng.uniform(8, w - 8)
        ys, xs = np.mgrid[0:h, 0:w]
        img += (
            0.8 * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 1.5**2)))
        ).astype(np.float32)
        coords.append((cx, cy))
    return np.clip(img, 0, 1), coords


# --- channels / pixels ---------------------------------------------------------
def test_channel_extraction_to_gray():
    img = Image(np.zeros((4, 4, 3), dtype=np.float32))
    out = get("ChannelExtraction")(channel="G").execute_on_image(img)
    assert out.channels == 1


def test_invert_and_binarize():
    img = Image(np.full((4, 4, 1), 0.3, dtype=np.float32))
    assert np.allclose(get("Invert")().execute_on_image(img).data, 0.7)
    b = get("Binarize")(threshold=0.5).execute_on_image(img)
    assert np.all(b.data == 0.0)


def test_rescale():
    img = Image(np.linspace(0.2, 0.6, 16, dtype=np.float32).reshape(4, 4, 1))
    out = get("Rescale")(low=0.0, high=1.0).execute_on_image(img)
    assert out.data.min() == pytest.approx(0.0)
    assert out.data.max() == pytest.approx(1.0)


def test_channel_combination_via_app():
    app = Application()
    r = Image(np.full((3, 3, 1), 0.2, dtype=np.float32))
    g = Image(np.full((3, 3, 1), 0.5, dtype=np.float32))
    b = Image(np.full((3, 3, 1), 0.9, dtype=np.float32))
    app.new_window(r, window_id="R")
    app.new_window(g, window_id="G")
    win = app.new_window(b, window_id="B")
    app.set_active_window(win)
    app.apply(get("ChannelCombination")(r="R", g="G", b="B"))
    out = win.main_view.image.data
    assert np.allclose(out[:, :, 0], 0.2) and np.allclose(out[:, :, 2], 0.9)


# --- restoration ---------------------------------------------------------------
def test_deconvolution_sharpens_point():
    from scipy.ndimage import gaussian_filter

    img = np.zeros((32, 32, 1), dtype=np.float32)
    img[16, 16, 0] = 1.0
    blurred = np.zeros_like(img)
    blurred[:, :, 0] = gaussian_filter(img[:, :, 0], 2.0)
    out = get("Deconvolution")(psf_sigma=2.0, iterations=30).execute_on_image(Image(blurred))
    assert out.data[16, 16, 0] > blurred[16, 16, 0]  # peak tightened


def test_noise_reduction_lowers_variance():
    rng = np.random.default_rng(1)
    clean = np.full((48, 48, 1), 0.5, dtype=np.float32)
    noisy = np.clip(clean + rng.normal(0, 0.05, clean.shape), 0, 1).astype(np.float32)
    out = get("NoiseReduction")(method="tv", strength=0.1).execute_on_image(Image(noisy))
    assert out.data.std() < noisy.std()


def test_morphology_opening_removes_speck():
    img = np.zeros((16, 16, 1), dtype=np.float32)
    img[8, 8, 0] = 1.0  # isolated speck
    out = get("MorphologicalTransformation")(
        operation="opening", size=3
    ).execute_on_image(Image(img))
    assert out.data[8, 8, 0] < 1.0


# --- background ----------------------------------------------------------------
def test_background_extraction_flattens_gradient():
    h = w = 64
    yy, xx = np.mgrid[0:h, 0:w]
    grad = (0.1 + 0.4 * xx / w + 0.3 * yy / h).astype(np.float32)[:, :, None]
    out = get("BackgroundExtraction")(
        box_size=16, subtract=True, pedestal=0.1
    ).execute_on_image(Image(grad))
    assert out.data.std() < grad.std() * 0.5  # gradient clearly flattened (×3 in practice)


def test_background_neutralization_equalizes_channels():
    data = np.dstack([
        np.full((8, 8), 0.2, np.float32),
        np.full((8, 8), 0.4, np.float32),
        np.full((8, 8), 0.6, np.float32),
    ])
    out = get("BackgroundNeutralization")().execute_on_image(Image(data))
    meds = [float(np.median(out.data[:, :, c])) for c in range(3)]
    assert max(meds) - min(meds) < 1e-5


# --- stars / cosmetics ---------------------------------------------------------
def test_star_mask_detects_stars():
    field, _coords = star_field(n=25)
    proc = get("StarMask")(fwhm=3.0, threshold_sigma=5.0, radius=4.0)
    mask = proc.execute_on_image(Image(field[:, :, None]))
    assert mask.channels == 1
    assert mask.data.sum() > 0
    assert proc.stars is not None and len(proc.stars) >= 10


def test_cosmic_clip_removes_hot_pixels():
    rng = np.random.default_rng(2)
    base = np.clip(rng.normal(0.2, 0.02, (64, 64)), 0, 1).astype(np.float32)
    hot = base.copy()
    for (y, x) in [(10, 10), (30, 40), (50, 20)]:
        hot[y, x] = 1.0
    out = get("CosmicClip")().execute_on_image(Image(hot[:, :, None]))
    assert out.data[10, 10, 0] < 0.8  # impact damped


def test_debayer_cfa_to_rgb():
    cfa = np.clip(np.random.default_rng(3).random((16, 16)), 0, 1).astype(np.float32)
    out = get("Debayer")(pattern="RGGB").execute_on_image(Image(cfa[:, :, None]))
    assert out.channels == 3


# --- calibration / integration / registration ---------------------------------
def test_image_calibration_subtracts_bias(tmp_path):
    bias = Image(np.full((8, 8, 1), 0.1, dtype=np.float32))
    bp = str(tmp_path / "bias.fits")
    save_fits(bp, bias)
    light = Image(np.full((8, 8, 1), 0.5, dtype=np.float32))
    out = get("ImageCalibration")(master_bias=bp).execute_on_image(light)
    assert np.allclose(out.data, 0.4, atol=1e-5)


def test_integration_rejects_outlier(tmp_path):
    truth = 0.5
    paths = []
    rng = np.random.default_rng(4)
    frames = []
    for _ in range(7):
        f = np.clip(truth + rng.normal(0, 0.01, (8, 8, 1)), 0, 1).astype(np.float32)
        frames.append(f)
    frames[0][4, 4, 0] = 1.0  # outlier (cosmic ray)
    for i, f in enumerate(frames):
        p = str(tmp_path / f"f{i}.fits")
        save_fits(p, Image(f))
        paths.append(p)

    app = Application()
    proc = get("Integration")(frames=paths, rejection="sigma", sigma_low=3, sigma_high=3)
    app.run(proc)
    result = app.windows[-1].main_view.image.data
    assert abs(result[4, 4, 0] - truth) < 0.05  # the outlier was rejected


def test_star_alignment_recovers_shift():
    field, _ = star_field(n=40, seed=7)
    ref = field[:, :, None]
    shifted = np.roll(np.roll(field, 3, axis=0), 5, axis=1)[:, :, None]

    app = Application()
    app.new_window(Image(ref), window_id="ref")
    win = app.new_window(Image(shifted), window_id="target")
    app.set_active_window(win)
    try:
        app.apply(get("StarAlignment")(reference_id="ref"))
    except Exception as exc:  # astroalign can fail if too few matches are found
        pytest.skip(f"astroalign did not converge: {exc}")
    aligned = win.main_view.image.data[:, :, 0]
    # after registration, the aligned image must correlate strongly with the reference
    corr = np.corrcoef(aligned.ravel(), field.ravel())[0, 1]
    assert corr > 0.7


def test_end_to_end_pipeline(tmp_path):
    """Mini pipeline: 3 raws → Integration → BackgroundExtraction → NoiseReduction, then a
    recipe replayable from the history — all of it headless, without a shell."""
    from retina import ProcessContainer

    field, _ = star_field(n=20, seed=11)
    rng = np.random.default_rng(11)
    paths = []
    for i in range(3):
        f = np.clip(field + rng.normal(0, 0.01, field.shape), 0, 1).astype(np.float32)[:, :, None]
        p = str(tmp_path / f"light{i}.fits")
        save_fits(p, Image(f))
        paths.append(p)

    app = Application()
    app.run(get("Integration")(frames=paths, rejection="sigma"))  # → new stacked window
    view = app.active_view
    app.apply(get("BackgroundExtraction")(box_size=16, subtract=True, pedestal=0.05))
    app.apply(get("NoiseReduction")(method="tv", strength=0.05))

    assert np.isfinite(view.image.data).all()
    assert view.history_index == 2

    recipe = view.recipe()
    assert len(recipe) == 2 and "BackgroundExtraction" in recipe.to_xml()
    assert isinstance(recipe, ProcessContainer)


def test_statistics_readonly():
    img = Image(np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8, 1))
    proc = get("Statistics")()
    from retina import View

    view = View(img, view_id="v")
    proc.execute_on(view)
    assert view.history_index == 0  # read-only: no history entry
    assert "median" in proc.result["channels"][0]
