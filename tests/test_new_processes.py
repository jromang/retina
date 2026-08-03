"""Tests for the processes built on top of the Python libraries.

Tier A (no extra dependency) + extensions, Tier B (reproject/sep), Tier C (pywt/cv2/sklearn),
plus the wavelet bug fix and the RAW io dispatch. All headless: behavioural assertions, not
just "it runs".
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image, get
from retina.process import context


# --- helpers ------------------------------------------------------------------
def _gradient(h=48, w=48, c=1):
    """Gentle linear ramp (a tilted background) in [0,1]."""
    ramp = np.linspace(0.1, 0.6, w, dtype=np.float32)[None, :]
    base = np.repeat(ramp, h, axis=0)
    return np.repeat(base[:, :, None], c, axis=2)


def _stars(h=48, w=48, c=1, centers=((24, 24),), sigma=2.0, noise=0.0, seed=0):
    rs = np.random.RandomState(seed)
    base = np.full((h, w, c), 0.1, np.float32) + rs.rand(h, w, c).astype(np.float32) * noise
    ys, xs = np.mgrid[0:h, 0:w]
    for (cx, cy) in centers:
        blob = np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma**2))).astype(np.float32)
        for ch in range(c):
            base[:, :, ch] += 0.7 * blob
    return np.clip(base, 0, 1)


@pytest.fixture
def provider():
    store: dict[str, Image] = {}
    context.set_image_provider(lambda name: store.get(name))
    yield store
    context.set_image_provider(None)


# =============================================================================
# Tier 0 — the wavelet bug
# =============================================================================
def test_wavelet_noise_reduction_no_longer_raises():
    data = _stars(noise=0.15, seed=3)
    out = get("NoiseReduction")(method="wavelet").execute_on_image(Image(data)).data
    assert out.var() < data.var()  # denoises → lower variance


# =============================================================================
# Tier A — new processes
# =============================================================================
def test_rolling_ball_flattens_gradient():
    data = _gradient()
    out = get("RollingBallBackground")(radius=15, subtract=True).execute_on_image(Image(data)).data
    # left→right background span sharply reduced
    assert out[:, -5:].mean() - out[:, :5].mean() < (data[:, -5:].mean() - data[:, :5].mean())


def test_nlmeans_denoise_lowers_variance():
    data = _stars(noise=0.15, seed=1)
    out = get("NonLocalMeansDenoise")().execute_on_image(Image(data)).data
    assert out.var() < data.var()


def test_phase_correlation_recovers_shift(provider):
    ref = _stars(centers=((20, 24),), seed=2)
    provider["ref"] = Image(ref)
    shifted = np.roll(np.roll(ref, 3, axis=0), 4, axis=1)  # +3 in y, +4 in x
    out = get("PhaseCorrelationAlignment")(reference_id="ref").execute_on_image(Image(shifted)).data
    py, px = np.unravel_index(int(np.argmax(out[:, :, 0])), out.shape[:2])
    assert abs(py - 24) <= 1 and abs(px - 20) <= 1


def test_histogram_matching_aligns_median(provider):
    ref = _stars(noise=0.05, seed=5) * 0.3 + 0.4  # shifted distribution
    provider["ref"] = Image(np.clip(ref, 0, 1))
    src = _stars(noise=0.05, seed=6)
    out = get("HistogramMatching")(reference="ref").execute_on_image(Image(src)).data
    assert abs(np.median(out) - np.median(provider["ref"].data)) < 0.05


def test_source_extraction_counts_stars():
    data = _stars(centers=((10, 10), (30, 35)), noise=0.01, seed=7)
    proc = get("SourceExtraction")(threshold_sigma=3, npixels=5)
    proc.execute_on_image(Image(data))
    assert proc.result["n_sources"] == 2


def test_pixel_interpolation_fills_nan():
    data = _stars(noise=0.0).copy()
    data[5, 5, 0] = np.nan
    out = get("PixelInterpolation")().execute_on_image(Image(data)).data
    assert not np.isnan(out).any()
    assert abs(out[5, 5, 0] - data[4, 4, 0]) < 0.1  # filled in from the neighbourhood


def test_radial_profile_measures_fwhm():
    data = _stars(centers=((24, 24),), sigma=2.5, noise=0.0)
    proc = get("RadialProfileMeasurement")(max_radius=12)
    proc.execute_on_image(Image(data))
    assert proc.result["fwhm"] is not None and proc.result["fwhm"] > 0


def test_galaxy_model_subtracts_core():
    # the "galaxy" is a broad, smooth gaussian
    h = w = 64
    ys, xs = np.mgrid[0:h, 0:w]
    gal = 0.8 * np.exp(-(((xs - 32) ** 2 + (ys - 32) ** 2) / (2 * 12.0**2)))
    data = np.clip(gal + 0.05, 0, 1).astype(np.float32)[:, :, None]
    out = get("GalaxyModel")(sma0=8, subtract=True).execute_on_image(Image(data)).data
    assert out[32, 32, 0] < data[32, 32, 0]  # the core is damped by the model


def test_satellite_trail_detection_finds_line():
    data = _stars(64, 64, noise=0.0, centers=())
    for i in range(64):
        data[i, i, 0] = 1.0  # diagonal trail at 45°
    proc = get("SatelliteTrailDetection")(width=2)
    mask = proc.execute_on_image(Image(data)).data
    assert mask.sum() > 30  # a straight line is masked
    assert 30.0 <= proc.angle_deg <= 60.0  # ~45° (to within the angular resolution)


def test_ricker_wavelet_changes_contrast():
    data = _stars(noise=0.0)
    out = get("RickerWaveletEnhance")(width=2, amount=2.0).execute_on_image(Image(data)).data
    assert not np.allclose(out, data)
    assert out[24, 24, 0] >= data[24, 24, 0] - 1e-3  # lifts the peak


# --- Tier A: extensions -------------------------------------------------------
@pytest.mark.parametrize("op", ["white_tophat", "black_tophat", "gradient"])
def test_morphology_new_ops(op):
    data = _stars(noise=0.02, seed=8)
    out = get("MorphologicalTransformation")(
        operation=op, size=3
    ).execute_on_image(Image(data)).data
    assert out.shape == data.shape


@pytest.mark.parametrize("estimator", ["sextractor", "mmm"])
def test_background_extraction_estimators(estimator):
    data = _gradient()
    out = get("BackgroundExtraction")(box_size=16, estimator=estimator, pedestal=0.0)
    res = out.execute_on_image(Image(data)).data
    span_in = float(data[:, -5:].mean() - data[:, :5].mean())
    span_out = float(res[:, -5:].mean() - res[:, :5].mean())
    assert span_out < span_in  # the chosen estimator flattens the gradient


def test_restoration_filter_unsupervised_runs():
    data = _stars(sigma=3.0, noise=0.0)
    out = get("RestorationFilter")(
        mode="unsupervised", psf_sigma=2.0
    ).execute_on_image(Image(data)).data
    assert out.shape == data.shape and np.isfinite(out).all()


def test_integer_resample_sum_conserves_flux():
    data = np.full((8, 8, 1), 0.1, np.float32)  # low values → no clipping
    avg = get("IntegerResample")(
        factor=2, downsample_op="average"
    ).execute_on_image(Image(data)).data
    summed = get("IntegerResample")(
        factor=2, downsample_op="sum"
    ).execute_on_image(Image(data)).data
    assert np.allclose(summed, 4 * avg, atol=1e-4)  # 2×2 sum = 4× the average


# =============================================================================
# Tier B — reproject / sep
# =============================================================================
def _wcs_fits(path, crval, shape=(60, 60)):
    from astropy.io import fits
    from astropy.wcs import WCS

    data = np.full(shape, 0.2, np.float32)
    data[25:35, 25:35] = 0.9
    w = WCS(naxis=2)
    w.wcs.crpix = [shape[1] / 2, shape[0] / 2]
    w.wcs.cdelt = [-0.001, 0.001]
    w.wcs.crval = crval
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    fits.PrimaryHDU(data, header=w.to_header()).writeto(path, overwrite=True)


def test_mosaic_reproject_widens_field(tmp_path):
    p1, p2 = tmp_path / "a.fits", tmp_path / "b.fits"
    _wcs_fits(str(p1), [150.00, 2.0])
    _wcs_fits(str(p2), [150.03, 2.0])  # field offset in RA (partial overlap)
    app = Application()
    app.run(get("MosaicReproject")(frames=[str(p1), str(p2)], new_image_id="mos"))
    img = app.windows[-1].main_view.image.data
    assert img.shape[1] > 60  # the mosaic spans wider than a single frame


def test_sep_background_flattens_gradient():
    data = _gradient()
    out = get("SEPBackground")(box_size=16, subtract=True).execute_on_image(Image(data)).data
    assert out[:, -5:].mean() - out[:, :5].mean() < (data[:, -5:].mean() - data[:, :5].mean())


def test_sep_source_extraction_counts_stars():
    data = _stars(64, 64, centers=((15, 15), (45, 40)), noise=0.01, seed=9)
    proc = get("SEPSourceExtraction")(threshold_sigma=4, min_area=4)
    proc.execute_on_image(Image(data))
    assert proc.result["n_sources"] == 2


# =============================================================================
# Tier C — pywt / cv2 / sklearn + io RAW
# =============================================================================
def test_wavelet_denoise_lowers_variance():
    data = _stars(noise=0.15, seed=10)
    out = get("WaveletDenoise")(level=3, threshold=3.0).execute_on_image(Image(data)).data
    assert out.var() < data.var()


def test_wavelet_transform_identity_roundtrip():
    data = _stars(noise=0.02, seed=11)
    out = get("WaveletTransform")(level=2, approx_gain=1.0, detail_gain=1.0)
    res = out.execute_on_image(Image(data)).data
    assert np.allclose(res, np.clip(data, 0, 1), atol=1e-4)  # neutral gains → identity


def test_fast_nlmeans_lowers_variance():
    data = _stars(noise=0.15, seed=12)
    out = get("FastNLMeansDenoise")(strength=5).execute_on_image(Image(data)).data
    assert out.var() < data.var()


def test_inpaint_fills_holes():
    data = _stars(noise=0.0)
    data[10:14, 10:14, 0] = 0.0  # a black hole
    out = get("Inpaint")(zero_threshold=0.001, radius=3).execute_on_image(Image(data)).data
    assert out[11, 11, 0] > 0.0  # filled in


def test_seamless_clone_runs():
    data = _stars(64, 64, 3, centers=((10, 10),), noise=0.05, seed=13)
    out = get("SeamlessClone")(src_x=10, src_y=10, dst_x=40, dst_y=40, radius=6)
    res = out.execute_on_image(Image(data)).data
    assert res.shape == data.shape and np.isfinite(res).all()


def test_feature_alignment_improves_correlation(provider):
    from scipy.ndimage import gaussian_filter

    rs = np.random.RandomState(14)
    tex = np.zeros((120, 120, 3), np.float32)
    for _ in range(60):  # high-contrast squares → ORB corners
        y, x, s = rs.randint(0, 110), rs.randint(0, 110), rs.randint(4, 10)
        tex[y:y + s, x:x + s, :] = rs.rand()
    tex = gaussian_filter(tex, (0.5, 0.5, 0))
    provider["ref"] = Image(tex)
    shifted = np.roll(np.roll(tex, 5, axis=0), 4, axis=1)

    def corr(a):
        return np.corrcoef(a[20:100, 20:100].ravel(), tex[20:100, 20:100].ravel())[0, 1]

    out = get("FeatureAlignment")(reference_id="ref").execute_on_image(Image(shifted)).data
    assert corr(out) > corr(shifted)  # registration brings it closer to the reference


@pytest.mark.parametrize("method", ["pca", "ica"])
def test_component_separation_shape_and_range(method):
    data = _stars(48, 48, 3, centers=((12, 12),), noise=0.05, seed=15)
    out = get("ComponentSeparation")(method=method).execute_on_image(Image(data)).data
    assert out.shape == data.shape
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_raw_extension_dispatch():
    """A RAW extension routes to load_raw (it fails while loading, not as 'unsupported')."""
    from retina.io import load_image_array
    from retina.io.raw import RAW_EXT

    assert ".cr2" in RAW_EXT and ".nef" in RAW_EXT
    with pytest.raises(Exception) as exc:
        load_image_array("/nonexistent/sample.cr2")
    assert "Unsupported" not in str(exc.value)


@pytest.mark.parametrize("channels", [1, 3])
def test_unsharp_mask_keeps_the_image_it_sharpens(channels):
    """It used to return a black frame — on every image, mono included.

    ``scikit-image`` 0.26's ``unsharp_mask`` returns garbage for ``channel_axis=-1``: an
    overflow warning from numpy, a mean of 235 out of an input at 0.18 on ``(H, W, 1)``, and
    a black frame on colour. The process had no test, so nothing said so. What is asserted
    here is the invariant of an unsharp mask — it redistributes local contrast, it does not
    change the overall level — plus the fact that it sharpens at all.
    """
    data = _stars(64, 64, channels, centers=((32, 32), (20, 44)), sigma=2.5, noise=0.02, seed=3)
    out = get("UnsharpMask")(radius=2.0, amount=0.8).execute_on_image(Image(data)).data

    assert np.isfinite(out).all()
    assert out.shape == data.shape
    assert abs(float(out.mean()) - float(data.mean())) < 0.05
    # sharpening raises the local gradient
    assert float(np.abs(np.diff(out, axis=0)).mean()) > float(np.abs(np.diff(data, axis=0)).mean())


def test_overscan_survives_a_section_that_does_not_span_the_frame():
    """Real headers do not promise a full-height BIASSEC.

    The Palomar frames shipped as Retina's own example dataset declare
    ``[2049:2080,1:4127]`` on a 4128-row sensor. One row short used to raise a bare numpy
    broadcast error in the middle of a pre-processing run, mentioning neither overscan nor
    the header that caused it.
    """
    from retina import Overscan

    data = np.zeros((40, 30, 1), dtype=np.float32)
    data[:, 25:30] = 5.0  # the overscan strip carries the read-out level
    data[:, :25] = 12.0

    # a section one row short of the frame, as the real headers write it
    out = Overscan(bias_section="[26:30,1:39]").execute_on_image(Image(data)).data

    assert out.shape == data.shape
    assert np.isfinite(out).all()
    # the level is removed everywhere, the unmeasured last row included
    np.testing.assert_allclose(out[:, :25], 7.0, atol=1e-5)
