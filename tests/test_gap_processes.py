"""Tests of the processes that close the remaining feature gap.

Everything is checked **headless** (without the shell), through ``execute_on_image`` and the
global helpers. Reference-taking processes use an image provider
(``context.set_image_provider``).
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image, get
from retina.io.fits import save_fits
from retina.process import context


@pytest.fixture
def provider():
    """Registers a provider of named images and cleans it up after the test."""
    store: dict[str, Image] = {}
    context.set_image_provider(lambda name: store.get(name))
    yield store
    context.set_image_provider(None)


@pytest.fixture
def rng():
    return np.random.default_rng(1234)


def _apply(pid, img, **kw):
    return get(pid)(**kw).execute_on_image(img).data


# --- P0: colour / stretch / masks ---------------------------------------------
def test_scnr_reduces_green():
    data = np.zeros((4, 4, 3), np.float32)
    data[..., 0], data[..., 1], data[..., 2] = 0.2, 0.9, 0.4  # dominant green
    out = _apply("SCNR", Image(data), channel="G", protection="average")
    assert np.all(out[..., 1] <= data[..., 1] + 1e-6)
    assert np.allclose(out[..., 1], np.minimum(0.9, (0.2 + 0.4) / 2))


def test_convert_gray_and_rgb_roundtrip():
    rgb = Image(np.full((3, 3, 3), 0.4, np.float32))
    gray = _apply("ConvertToGrayscale", rgb)
    assert gray.shape == (3, 3, 1)
    back = _apply("ConvertToRGBColor", Image(gray))
    assert back.shape == (3, 3, 3)
    assert np.allclose(back[..., 0], back[..., 2])


def test_color_saturation_zero_desaturates(rng):
    rgb = Image((rng.random((8, 8, 3)) * 0.8 + 0.1).astype(np.float32))
    out = _apply("ColorSaturation", rgb, saturation=0.0)
    assert np.allclose(out[..., 0], out[..., 1], atol=1e-4)
    assert np.allclose(out[..., 1], out[..., 2], atol=1e-4)


def test_arcsinh_brightens_and_is_monotone():
    gray = Image(np.linspace(0.0, 1.0, 64, dtype=np.float32).reshape(8, 8, 1))
    out = _apply("ArcsinhStretch", gray, stretch=20.0)
    assert out.mean() > gray.mean()
    assert np.all(np.diff(out.ravel()) >= -1e-6)
    assert out.ravel()[0] == pytest.approx(0.0, abs=1e-6)


def test_autohistogram_raises_median_toward_target():
    gray = Image(np.full((16, 16, 1), 0.02, np.float32) +
                 np.linspace(0, 0.04, 256).reshape(16, 16, 1).astype(np.float32))
    out = _apply("AutoHistogram", gray, target_background=0.25)
    assert np.median(out) > np.median(gray.data)


def test_exponential_endpoints_fixed_and_direction():
    gray = Image(np.linspace(0.0, 1.0, 25, dtype=np.float32).reshape(5, 5, 1))
    pip = _apply("ExponentialTransformation", gray, type="PIP", order=2.0)
    smi = _apply("ExponentialTransformation", gray, type="SMI", order=2.0)
    for out in (pip, smi):
        assert out.ravel()[0] == pytest.approx(0.0, abs=1e-6)
        assert out.ravel()[-1] == pytest.approx(1.0, abs=1e-6)
    assert pip.mean() > gray.mean()   # PIP brightens
    assert smi.mean() < gray.mean()   # SMI darkens


def test_range_selection_selects_band():
    grad = np.linspace(0.0, 1.0, 100, dtype=np.float32).reshape(10, 10)
    mask = _apply("RangeSelection", Image(grad[:, :, None]), lower=0.4, upper=0.6)
    assert mask.shape == (10, 10, 1)
    sel = grad[mask[..., 0] > 0.5]
    assert sel.min() >= 0.4 - 1e-6 and sel.max() <= 0.6 + 1e-6


# --- P1: geometry / multiscale ------------------------------------------------
def test_crop_and_resample_shapes():
    img = Image(np.zeros((20, 40, 3), np.float32))
    assert _apply("Crop", img, x0=0.25, y0=0.5, x1=0.75, y1=1.0).shape == (10, 20, 3)
    assert _apply("Resample", img, scale=0.5).shape == (10, 20, 3)


def test_integer_resample_downsample_averages():
    img = Image(np.full((8, 8, 1), 0.5, np.float32))
    down = _apply("IntegerResample", img, factor=2, mode="downsample")
    assert down.shape == (4, 4, 1)
    assert np.allclose(down, 0.5)
    up = _apply("IntegerResample", img, factor=2, mode="upsample")
    assert up.shape == (16, 16, 1)


def test_fast_rotation_is_lossless(rng):
    img = Image((rng.random((6, 8, 1))).astype(np.float32))
    r90 = get("FastRotation")(operation="rotate90")
    x = img.data
    for _ in range(4):
        x = r90.execute_on_image(Image(x)).data
    assert np.allclose(x, img.data)  # 4×90° = identity
    hm = _apply("FastRotation", img, operation="hmirror")
    assert np.allclose(_apply("FastRotation", Image(hm), operation="hmirror"), img.data)


def test_mmt_reconstruction_is_identity(rng):
    gray = Image((rng.random((16, 16, 1)) * 0.8 + 0.1).astype(np.float32))
    out = _apply("MultiscaleMedianTransform", gray, scales=4)
    # empty bias + zero threshold = faithful reconstruction
    assert np.allclose(out, gray.data, atol=1e-5)


def test_hdrmt_runs_in_range(rng):
    gray = Image((rng.random((16, 16, 1))).astype(np.float32))
    out = _apply("HDRMultiscaleTransform", gray, layers=4, overdrive=0.3)
    assert np.isfinite(out).all() and out.min() >= -1e-6 and out.max() <= 1 + 1e-6


# --- P1: reference-taking processes -------------------------------------------
def test_linear_fit_recovers_reference(provider, rng):
    data = (rng.random((8, 8, 1)) * 0.5 + 0.2).astype(np.float32)
    ref = np.clip(0.5 * data + 0.15, 0, 1).astype(np.float32)
    provider["ref"] = Image(ref)
    out = _apply("LinearFit", Image(data), reference="ref")
    assert np.allclose(out, ref, atol=1e-4)


def test_color_calibration_equalizes_channel_means(provider, rng):
    data = (rng.random((16, 16, 3)) * 0.3).astype(np.float32)
    data[..., 1] += 0.1  # green cast
    out = _apply("ColorCalibration", Image(data))
    before = np.std([data[..., c].mean() for c in range(3)])
    after = np.std([out[..., c].mean() for c in range(3)])
    assert after < before


def test_lrgb_combination_uses_luminance(provider, rng):
    rgb = Image((rng.random((8, 8, 3)) * 0.4 + 0.1).astype(np.float32))
    provider["L"] = Image(np.full((8, 8, 1), 0.8, np.float32))
    out = _apply("LRGBCombination", rgb, luminance="L", weight=1.0)
    assert out.shape == (8, 8, 3) and np.isfinite(out).all()


# --- P2: preprocessing --------------------------------------------------------
def test_cosmetic_correction_removes_hot_pixel():
    data = np.full((16, 16, 1), 0.1, np.float32)
    data[8, 8, 0] = 1.0  # hot pixel
    out = _apply("CosmeticCorrection", Image(data), hot_sigma=3.0)
    assert out[8, 8, 0] < 0.3


def test_superbias_reduces_noise(rng):
    noisy = (0.5 + rng.normal(0, 0.05, (32, 32, 1))).astype(np.float32)
    out = _apply("Superbias", Image(np.clip(noisy, 0, 1)), noise_layers=5)
    assert out.var() < noisy.var()


def test_splitcfa_mergecfa_roundtrip(rng):
    mosaic = Image((rng.random((16, 16, 1))).astype(np.float32))
    planes = _apply("SplitCFA", mosaic)
    assert planes.shape == (8, 8, 4)
    merged = _apply("MergeCFA", Image(planes))
    assert np.allclose(merged, mosaic.data)


def test_local_normalization_matches_background(provider, rng):
    ref = np.full((32, 32, 1), 0.3, np.float32)
    data = (np.full((32, 32, 1), 0.1) + rng.normal(0, 0.02, (32, 32, 1))).astype(np.float32)
    provider["ref"] = Image(np.clip(ref, 0, 1))
    out = _apply("LocalNormalization", Image(np.clip(data, 0, 1)), reference="ref", scale=16.0)
    assert abs(float(np.median(out)) - 0.3) < 0.05  # background matched onto the reference


def test_subframe_selector_weights_sum_to_one(tmp_path, rng):
    proc = get("SubframeSelector")(fwhm=2.5, threshold_sigma=4.0)
    paths = []
    for i in range(3):
        img = np.full((48, 48), 0.05, np.float32)
        yy, xx = np.mgrid[0:48, 0:48]
        for cx, cy in [(10, 12), (30, 20), (40, 40)][: i + 1]:  # varying star count
            img += 0.7 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / 8.0)
        p = str(tmp_path / f"f{i}.fits")
        save_fits(p, Image(np.clip(img, 0, 1)[:, :, None]))
        paths.append(p)
    proc.frames = paths
    rows = proc.measure()
    assert len(rows) == 3
    assert sum(r["weight"] for r in rows) == pytest.approx(1.0, abs=1e-6)


def test_drizzle_integration_creates_upsampled_window(tmp_path):
    app = Application()
    paths = []
    for i in range(2):
        p = str(tmp_path / f"d{i}.fits")
        save_fits(p, Image(np.full((8, 8, 1), 0.4, np.float32)))
        paths.append(p)
    app.run(get("DrizzleIntegration")(frames=paths, scale=2, new_image_id="driz"))
    win = app.windows[-1]
    assert win.main_view.image.data.shape == (16, 16, 1)
    assert np.allclose(win.main_view.image.data, 0.4, atol=1e-3)


# --- P3: denoising / gradient / PSF / restoration / Fourier -------------------
def test_acdnr_lowers_background_noise(rng):
    img = np.full((32, 32, 1), 0.3, np.float32) + rng.normal(
        0, 0.05, (32, 32, 1)
    ).astype(np.float32)
    out = _apply("ACDNR", Image(np.clip(img, 0, 1)), sigma=2.0, protection=0.2)
    assert out.var() < img.var()


def test_tgv_denoise_recovers_ramp_without_staircasing(rng):
    # true TGV²: denoises a smooth ramp WITHOUT creating steps (unlike TV)
    _yy, xx = np.mgrid[0:40, 0:40]
    clean = (0.2 + 0.6 * xx / 40).astype(np.float32)[:, :, None]
    noisy = np.clip(clean + rng.normal(0, 0.05, clean.shape), 0, 1).astype(np.float32)
    out = _apply("TGVDenoise", Image(noisy), strength=0.05, iterations=150)
    assert ((out - clean) ** 2).mean() < 0.3 * ((noisy - clean) ** 2).mean()  # clear denoising

    def sd(a):  # second-derivative energy along x = a measure of the staircasing effect
        return np.mean(np.diff(a[:, :, 0], 2, axis=1) ** 2)

    assert sd(out) < 0.05 * sd(noisy)  # stays as smooth as the clean ramp


def test_gradient_correction_flattens_ramp():
    _yy, xx = np.mgrid[0:40, 0:40]
    ramp = (0.2 + 0.5 * xx / 40).astype(np.float32)[:, :, None]
    out = _apply("GradientCorrection", Image(ramp), degree=1, pedestal=0.1)
    assert out.std() < ramp.std()  # gradient removed → flatter


def test_multiscale_gradient_correction_runs():
    yy, _xx = np.mgrid[0:32, 0:32]
    ramp = (0.2 + 0.4 * yy / 32).astype(np.float32)[:, :, None]
    out = _apply("MultiscaleGradientCorrection", Image(ramp), scale=5)
    assert np.isfinite(out).all()


def test_gradient_merge_mosaic_blends(provider):
    a = np.zeros((10, 10, 1), np.float32)
    b = np.zeros((10, 10, 1), np.float32)
    a[:, :6] = 0.5   # left panel
    b[:, 4:] = 0.5   # right panel (columns 4-5 overlap)
    provider["b"] = Image(b)
    out = _apply("GradientMergeMosaic", Image(a), other="b")
    assert out[0, 0, 0] == pytest.approx(0.5, abs=1e-3)   # area A only
    assert out[0, 9, 0] == pytest.approx(0.5, abs=1e-3)   # area B only


def test_restoration_filter_runs(rng):
    img = np.clip(rng.random((24, 24, 1)) * 0.5 + 0.1, 0, 1).astype(np.float32)
    out = _apply("RestorationFilter", Image(img), psf_sigma=1.5, balance=0.2)
    assert np.isfinite(out).all() and out.shape == img.shape


def test_dynamic_psf_measures_fwhm():
    img = np.full((64, 64), 0.05, np.float32)
    yy, xx = np.mgrid[0:64, 0:64]
    for cx, cy in [(12, 15), (40, 20), (50, 50), (20, 45)]:
        img += 0.8 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 2.0 ** 2))
    proc = get("DynamicPSF")(fwhm=2.5)
    proc.measure(Image(np.clip(img, 0, 1)[:, :, None]))
    assert proc.result["n_stars"] > 0
    assert proc.result["fwhm"] is not None and proc.result["fwhm"] > 0


def test_fourier_magnitude_in_range():
    img = np.zeros((16, 16, 1), np.float32)
    img[8, 8, 0] = 1.0  # point source
    out = _apply("FourierTransform", Image(img), mode="magnitude")
    assert out.shape == (16, 16, 1)
    assert out.min() >= -1e-6 and out.max() <= 1 + 1e-6


def test_fourier_complex_roundtrip_is_exact(rng):
    for shape in [(16, 16, 1), (12, 20, 3)]:
        img = Image(rng.random(shape).astype(np.float32))
        spec = _apply("FourierTransform", img, mode="complex")
        assert spec.shape[2] == 2 * shape[2]
        back = _apply("InverseFourierTransform", Image(spec))
        assert np.abs(back - img.data).max() < 1e-5  # faithful reconstruction (phase carried)


# --- P4: noise / retouch / HDR / comet / utilities ----------------------------
def test_noise_generator_adds_noise_deterministically():
    flat = Image(np.full((16, 16, 1), 0.5, np.float32))
    a = _apply("NoiseGenerator", flat, type="gaussian", amount=0.05, seed=42)
    b = _apply("NoiseGenerator", flat, type="gaussian", amount=0.05, seed=42)
    assert a.var() > 0  # noise was indeed added
    assert np.allclose(a, b)  # same seed → reproducible


def test_simplex_noise_is_smooth_and_in_range():
    flat = Image(np.full((32, 32, 1), 0.5, np.float32))
    out = _apply("SimplexNoise", flat, octaves=4, scale=8, amount=1.0, seed=1)
    assert out.min() >= -1e-6 and out.max() <= 1 + 1e-6
    # smooth: local variation far lower than white noise
    assert np.mean(np.abs(np.diff(out[:, :, 0], axis=1))) < 0.1


def test_clone_stamp_copies_patch():
    data = np.zeros((32, 32, 1), np.float32)
    data[5, 5, 0] = 1.0  # bright source
    out = _apply("CloneStamp", Image(data), src_x=5, src_y=5, dst_x=20, dst_y=20,
                 radius=3, softness=0.1)
    assert out[20, 20, 0] > 0.5  # the dot was cloned to the destination


def test_sample_format_conversion_quantizes():
    gray = Image(np.linspace(0, 1, 256, dtype=np.float32).reshape(16, 16, 1))
    q = _apply("SampleFormatConversion", gray, bits="8")
    assert np.allclose(q * 255, np.rint(q * 255))  # exact 8-bit levels
    assert len(np.unique(q)) <= 256


def test_larson_sekanina_zero_on_symmetric():
    # a centrally symmetric source (centred gaussian) → near-null response (centred on 0.5)
    yy, xx = np.mgrid[0:33, 0:33]
    g = np.exp(-((xx - 16) ** 2 + (yy - 16) ** 2) / (2 * 5.0 ** 2)).astype(np.float32)
    out = _apply("LarsonSekanina", Image(g[:, :, None]), angle=5.0)
    assert abs(float(out.mean()) - 0.5) < 0.05


def test_new_image_creates_filled_window():
    app = Application()
    app.run(get("NewImage")(width=10, height=8, channels=3, fill=0.2, new_image_id="blank"))
    img = app.windows[-1].main_view.image
    assert img.data.shape == (8, 10, 3)
    assert np.allclose(img.data, 0.2)


def test_image_identifier_and_fits_header():
    app = Application()
    win = app.new_window(Image(np.zeros((4, 4, 1), np.float32)), window_id="orig")
    get("ImageIdentifier")(new_id="renamed").execute_on(win.main_view)
    assert win.main_view.id == "renamed" and win.id == "renamed"
    get("FITSHeader")(keyword="OBJECT", value="M42").execute_on(win.main_view)
    assert win.keywords["OBJECT"] == "M42"


def test_hdr_and_fast_integration(tmp_path):
    app = Application()
    paths = []
    for i in range(3):
        p = str(tmp_path / f"e{i}.fits")
        save_fits(p, Image(np.full((12, 12, 1), 0.1 * (i + 1), np.float32)))
        paths.append(p)
    app.run(get("FastIntegration")(frames=paths, combine="median", new_image_id="fast"))
    assert float(app.windows[-1].main_view.image.data.mean()) == pytest.approx(0.2, abs=1e-3)
    app.run(get("HDRComposition")(frames=paths, new_image_id="hdr"))
    assert app.windows[-1].main_view.image.data.shape == (12, 12, 1)


def test_comet_alignment_keeps_static_comet(tmp_path):
    app = Application()
    paths = []
    for i in range(3):
        f = np.zeros((16, 16, 1), np.float32)
        f[8, 8, 0] = 0.9  # motionless nucleus (null velocity)
        p = str(tmp_path / f"c{i}.fits")
        save_fits(p, Image(f))
        paths.append(p)
    app.run(get("CometAlignment")(frames=paths, vx=0.0, vy=0.0, new_image_id="comet"))
    assert app.windows[-1].main_view.image.data[8, 8, 0] == pytest.approx(0.9, abs=1e-3)
