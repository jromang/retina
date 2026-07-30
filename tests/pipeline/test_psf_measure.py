"""Quality measurement by **PSF fitting** — against ground truth.

FWHM used to be a proxy: DAOStarFinder's "sharpness", which is not a full width at half
maximum and which the code itself called a proxy. We now fit an elliptical Gaussian on each
star, as the established astrophotography suites do.

These tests synthesize stars of a **known** shape and check that we recover it. That is the
only way to test a fit: an assertion along the lines of "it returns a number" would have let
through the trap that cost the most time here — photutils **freezes** the shape parameters
of its PSF models, so an unprepared fit returned exactly the initial value, with every
appearance of having converged.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("photutils")

from retina.processes.psf import fit_psf_stars, pixel_scale
from retina.processes.subframe import SubframeSelector

SIZE = 160
BACKGROUND = 0.01
NOISE = 3e-4


def field(fwhm_x: float, fwhm_y: float, theta: float = 0.0, n: int = 24) -> np.ndarray:
    """A field of identical stars, of imposed shape — the ground truth."""
    from photutils.psf import GaussianPSF
    from retina.processes.psf import _free_shape

    rng = np.random.default_rng(11)
    image = np.full((SIZE, SIZE), BACKGROUND, dtype=np.float64)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(float)
    for x0, y0 in rng.uniform(16, SIZE - 16, size=(n, 2)):
        model = _free_shape(GaussianPSF(flux=20.0, x_0=x0, y_0=y0, x_fwhm=fwhm_x,
                                         y_fwhm=fwhm_y, theta=theta))
        image += model(xx, yy)
    image += rng.normal(0.0, NOISE, image.shape)
    return image.astype(np.float32)[:, :, np.newaxis]


def measure(image: np.ndarray, **kwargs) -> dict:
    return SubframeSelector(**kwargs).measure_array(image)


# --- the fit recovers the injected shape ----------------------------------------------

def test_the_fitted_fwhm_recovers_the_injected_value():
    m = measure(field(4.0, 4.0))

    assert m["fwhm"] == pytest.approx(4.0, abs=0.15)
    assert m["psf_count"] > 5


def test_the_fitted_eccentricity_recovers_the_elongation():
    """√(1 − (b/a)²) for a=6, b=3 is 0.866 — that is the value that must come out, not an
    order of magnitude."""
    m = measure(field(6.0, 3.0))

    assert m["eccentricity"] == pytest.approx(0.866, abs=0.05)


def test_elongation_is_seen_whatever_its_orientation():
    """A tracking drift has no reason to line up with the sensor axes."""
    right = measure(field(6.0, 3.0, theta=0.0))["eccentricity"]
    oblique = measure(field(6.0, 3.0, theta=np.pi / 4))["eccentricity"]

    assert oblique == pytest.approx(right, abs=0.05)


def test_a_blurred_frame_is_told_apart_from_a_sharp_one():
    """Ranking rests entirely on this: two FWHM values must order correctly."""
    sharp = measure(field(3.0, 3.0))["fwhm"]
    blurred = measure(field(5.0, 5.0))["fwhm"]

    assert blurred > sharp + 1.0


def test_the_fits_are_capped_by_the_parameter():
    m = measure(field(4.0, 4.0, n=40), max_fit_stars=5)

    assert m["psf_count"] <= 5


def test_the_number_of_fits_never_exceeds_the_detections():
    m = measure(field(4.0, 4.0))

    assert m["psf_count"] <= m["stars"]


# --- PSF uniformity across the field --------------------------------------------------

def test_a_homogeneous_field_has_a_low_mean_deviation():
    """Mean deviation measures tilt and coma, not the quality of the frame."""
    m = measure(field(4.0, 4.0))

    assert m["fwhm_mean_dev"] < 0.3
    assert m["eccentricity_mean_dev"] < 0.1


# --- moments fallback -----------------------------------------------------------------

def test_moments_mode_performs_no_fit():
    m = measure(field(4.0, 4.0), psf_model="moments")

    assert m["psf_count"] == 0
    assert m["eccentricity"] >= 0.0  # the moments are still computed


def test_a_starless_image_does_not_raise():
    """A flat, a misfiled dark: the measurement must return something, not blow up."""
    empty = np.full((64, 64, 1), BACKGROUND, dtype=np.float32)

    m = measure(empty)

    assert m["stars"] == 0
    assert m["psf_count"] == 0
    assert m["fwhm"] > 0.0


# --- scale in arcseconds --------------------------------------------------------------

def test_the_scale_follows_the_usual_formula():
    # ASI2600 (3.76 µm) on a 530 mm refractor: 1.46"/px, the value every calculator gives
    assert pixel_scale(3.76, 530.0) == pytest.approx(1.463, abs=0.005)
    assert pixel_scale(0.0, 530.0) == 0.0
    assert pixel_scale(3.76, 0.0) == 0.0


def test_the_fwhm_in_arcsec_is_a_conversion_of_the_fwhm_in_pixels():
    rows = [{"frame": "/a.fits", "stars": 10, "fwhm": 4.0, "eccentricity": 0.2,
             "noise": 1e-3, "snr": 20.0, "median": 0.01}]

    SubframeSelector(pixel_size=3.76, focal_length=530.0).evaluate(rows)

    assert rows[0]["fwhm_arcsec"] == pytest.approx(4.0 * 1.463, abs=0.01)


def test_without_a_known_scale_the_column_does_not_exist():
    """No value beats a made-up one: a wrong FWHM in arcsec ends up compared against
    measurements from other instruments."""
    rows = [{"frame": "/a.fits", "stars": 10, "fwhm": 4.0, "eccentricity": 0.2,
             "noise": 1e-3, "snr": 20.0, "median": 0.01}]

    SubframeSelector().evaluate(rows)

    assert "fwhm_arcsec" not in rows[0]


def test_the_entered_scale_wins_over_the_one_from_the_header():
    rows = [{"frame": "/a.fits", "stars": 10, "fwhm": 4.0, "eccentricity": 0.2,
             "noise": 1e-3, "snr": 20.0, "median": 0.01, "pixel_scale": 9.99}]

    SubframeSelector(pixel_size=3.76, focal_length=530.0).evaluate(rows)

    assert rows[0]["fwhm_arcsec"] == pytest.approx(4.0 * 1.463, abs=0.01)


def test_fixing_the_focal_length_does_not_trigger_a_remeasure():
    """The scale converts, it does not measure: it stays out of the cache fingerprint."""
    a = SubframeSelector(frames=["/a.fits"], focal_length=530.0).cache_values()
    b = SubframeSelector(frames=["/a.fits"], focal_length=1000.0).cache_values()

    assert a == b


def test_changing_the_psf_model_triggers_a_remeasure():
    """The flip side: that one really is a different measurement."""
    a = SubframeSelector(frames=["/a.fits"], psf_model="gaussian").cache_values()
    b = SubframeSelector(frames=["/a.fits"], psf_model="moments").cache_values()

    assert a != b


# --- compatibility with measurements already written ----------------------------------

def test_earlier_measurements_remain_evaluable():
    """A file written before PSF fitting existed lacks those columns: rejudging it must
    neither raise, nor invent a zero that would read as "perfect"."""
    rows = [{"frame": f"/f{i}.fits", "stars": 100 + i, "fwhm": 3.0 + 0.1 * i,
             "eccentricity": 0.3, "noise": 1e-3, "snr": 20.0, "median": 0.01}
            for i in range(4)]

    SubframeSelector().evaluate(rows)

    assert all(r["weight"] > 0 for r in rows)
    assert "psf_count" not in rows[0]
    assert "psf_count_sigma" not in rows[0]
    assert "fwhm_sigma" in rows[0]  # the quantities that are present are properly derived


# --- the shared building block ---------------------------------------------------------

def test_dynamic_psf_and_the_selector_share_the_same_fit():
    """Two implementations would have diverged — on the quantity used to rank frames."""
    from retina.model.image import Image
    from retina.processes.psf import DynamicPSF

    image = field(4.0, 4.0)
    by_the_process = DynamicPSF().measure(Image(image))
    by_the_selector = measure(image)

    assert by_the_process["fwhm"] == pytest.approx(by_the_selector["fwhm"], abs=0.2)


def test_a_runaway_fit_is_discarded():
    """A width larger than the cutout is not a wide star, it is a fit that went off the
    rails: including it would drag the median without a word."""
    flat = np.full((64, 64), BACKGROUND, dtype=np.float32)

    stars = fit_psf_stars(flat, [32.0], [32.0], fwhm_guess=3.0, background=BACKGROUND)

    assert stars == []


# --- signal metrics (PSF Signal Weight, PSF SNR) --------------------------------------
#
# The formulas and their constants are the published ones; the estimators that feed them are
# ours. Absolute values therefore do not coincide from one piece of software to the next —
# only the ranking within a batch counts, and that is what these tests check.

def test_the_formulas_are_the_published_ones():
    """The constants are not approximations: they are the published values, digit for digit."""
    from retina.processes.psf import psf_signal_weight, psf_snr

    expected_sw = (5.326e-6 * 100.0 * 7.0) / (9.0e6 * 0.002 * 0.05)
    assert psf_signal_weight(100.0, 7.0, 0.05, 0.002) == pytest.approx(expected_sw)

    expected_snr = (1.316e-7 * 100.0 * 100.0) / (4.987e6 * 0.002 * 0.002)
    assert psf_snr(100.0, 0.002) == pytest.approx(expected_snr)


def test_the_signal_metrics_are_zero_without_noise_or_background():
    """Dividing by zero would return an infinity that contaminates any batch normalization."""
    from retina.processes.psf import psf_signal_weight, psf_snr

    assert psf_signal_weight(100.0, 7.0, 0.0, 0.002) == 0.0
    assert psf_signal_weight(100.0, 7.0, 0.05, 0.0) == 0.0
    assert psf_snr(100.0, 0.0) == 0.0


def test_m_star_and_n_star_recover_the_background_and_the_noise():
    """M* has to survive a gradient: that is the whole point of a large-scale model."""
    from retina.processes.psf import local_background_residual, m_star, n_star

    rng = np.random.default_rng(5)
    gradient = np.linspace(0.01, 0.03, 400)[None, :] * np.ones((300, 1))
    image = (gradient + rng.normal(0.0, 1e-3, (300, 400))).astype(np.float32)

    residual = local_background_residual(image)

    assert m_star(residual) == pytest.approx(0.02, abs=0.002)
    # N* is not σ but ≈ 1.675 σ — it is a defined quantity, and the constants of PSFSW and
    # PSFSNR account for it.
    assert n_star(residual) == pytest.approx(1.675 * 1e-3, rel=0.25)


def test_a_uniform_image_produces_no_residual():
    from retina.processes.psf import local_background_residual, m_star, n_star

    residual = local_background_residual(np.full((128, 128), 0.01, dtype=np.float32))

    assert residual.size == 0
    assert m_star(residual) == 0.0 and n_star(residual) == 0.0


def test_haze_is_penalized_by_psfsw_and_invisible_to_psfsnr():
    """The case that justifies the metric.

    Haze or the Moon lift the background without adding anything to the signal. The
    signal-to-noise ratio knows nothing about it: neither the star flux nor the noise has
    moved. PSFSW divides by M*, so it drops — which is exactly what we ask of it.
    """
    clear = field(4.0, 4.0)
    hazy = (clear + 0.02).astype(np.float32)

    a = measure(clear)
    b = measure(hazy)

    assert b["m_star"] > 2 * a["m_star"], "the background must indeed have risen"
    assert b["psf_snr"] == pytest.approx(a["psf_snr"], rel=0.05), "the SNR sees nothing"
    assert b["psf_signal_weight"] < 0.5 * a["psf_signal_weight"]


def test_without_a_fitted_star_the_signal_metrics_are_absent():
    """They make no sense without photometry — and the background model would be computed
    only to produce a misleading value."""
    m = measure(np.full((64, 64, 1), BACKGROUND, dtype=np.float32))

    assert "psf_signal_weight" not in m
    assert "m_star" not in m


def test_the_mean_flux_really_divides_by_the_pixel_count():
    """ΣF̄ is a sum of means, not the mean of a sum."""
    m = measure(field(4.0, 4.0))

    assert m["psf_mean_signal"] < m["psf_signal"]
    assert m["psf_mean_signal"] > 0.0


def test_the_reference_weighting_is_expressible_with_our_variables():
    """The reference implementation normalizes PSFSignalWeight by its **maximum** alone, not
    min-max — and our `_max` variables let it be written exactly as is."""
    rows = [{"frame": f"/f{i}.fits", "stars": 100, "fwhm": 3.0 + 0.1 * i,
             "eccentricity": 0.3, "noise": 1e-3, "snr": 20.0, "median": 0.01,
             "psf_signal_weight": 1.0 + i, "psf_snr": 2.0 + i} for i in range(4)]
    formula = ("65 + 5 * fwhm_n + 10 * eccentricity_n + 20 * snr_n"
               " + 30 * psf_signal_weight / psf_signal_weight_max")

    SubframeSelector(weighting=formula).evaluate(rows)

    assert all(r["score"] > 0 for r in rows)
    # the best frame on that criterion is the last one: it reaches the maximum, hence a full 30
    assert rows[3]["psf_signal_weight_max"] == 4.0


# --- Moffat profile --------------------------------------------------------------------
#
# The reference suites offer Gaussian and Moffat; astropy and photutils only ship a
# **circular** Moffat, which would return no eccentricity at all — the quantity that weighs
# twice as much as FWHM. The elliptical model is therefore written here, and these tests check
# that it recovers an injected Moffat profile: width, elongation **and** β.

def moffat_field(fwhm_x: float, fwhm_y: float, beta: float, theta: float = 0.0,
                 n: int = 20) -> np.ndarray:
    from retina.processes.psf import _make_moffat

    Moffat = _make_moffat()
    rng = np.random.default_rng(4)
    image = np.full((SIZE, SIZE), BACKGROUND, dtype=np.float64)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(float)
    for x0, y0 in rng.uniform(16, SIZE - 16, size=(n, 2)):
        image += Moffat(flux=20.0, x_0=x0, y_0=y0, x_fwhm=fwhm_x, y_fwhm=fwhm_y,
                        theta=theta, beta=beta)(xx, yy)
    image += rng.normal(0.0, NOISE, image.shape)
    return image.astype(np.float32)[:, :, np.newaxis]


def test_the_moffat_recovers_the_injected_width():
    m = measure(moffat_field(4.0, 4.0, 2.5), psf_model="moffat")

    assert m["fwhm"] == pytest.approx(4.0, abs=0.15)
    assert m["psf_count"] > 5


def test_the_moffat_recovers_the_elongation():
    m = measure(moffat_field(6.0, 3.0, 2.5), psf_model="moffat")

    assert m["eccentricity"] == pytest.approx(0.866, abs=0.05)


def test_the_moffat_really_fits_its_beta():
    """β is what tells a broad-winged profile from a near-Gaussian one: freezing it would
    miss precisely what the Moffat brings."""
    from astropy.stats import sigma_clipped_stats
    from photutils.detection import DAOStarFinder
    from retina.processes.psf import fit_psf_stars

    for beta in (2.0, 4.0):
        image = moffat_field(4.0, 4.0, beta)[:, :, 0]
        _, background, deviation = sigma_clipped_stats(image, sigma=3.0)
        sources = DAOStarFinder(fwhm=4.0, threshold=5 * deviation)(image - background)
        cx = "x_centroid" if "x_centroid" in sources.colnames else "xcentroid"
        cy = "y_centroid" if "y_centroid" in sources.colnames else "ycentroid"

        stars = fit_psf_stars(image, sources[cx], sources[cy], fwhm_guess=4.0,
                                background=float(background), function="moffat")

        assert np.median([e["beta"] for e in stars]) == pytest.approx(beta, abs=0.3)


def test_the_choice_of_profile_triggers_a_remeasure():
    a = SubframeSelector(frames=["/a.fits"], psf_model="gaussian").cache_values()
    b = SubframeSelector(frames=["/a.fits"], psf_model="moffat").cache_values()

    assert a != b


def test_both_profiles_measure_the_same_signal_area():
    """The integration region is expressed in FWHM and not in σ: without that, Gaussian and
    Moffat would integrate different areas and their signals would not compare."""
    image = field(4.0, 4.0)

    gauss = measure(image, psf_model="gaussian")
    moffat = measure(image, psf_model="moffat")

    assert moffat["psf_signal"] == pytest.approx(gauss["psf_signal"], rel=0.15)
