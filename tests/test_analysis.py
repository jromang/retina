"""Inspecting the optical quality of the field.

The test field carries a **known defect**: stars grow softer and more elongated towards the
right, as if under sensor tilt. A measurement that fails to recover it measures nothing, and
this is the only way to know — a plausible FWHM never proves it is correct.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.model.window import ImageWindow
from retina.process.registry import get
from retina.processes.analysis import FIELD_MAP_TAG

pytest.importorskip("photutils")


def tilted_field(size=400, n=220, seed=4):
    """Stars getting softer and more elongated towards the right."""
    from scipy.ndimage import gaussian_filter1d

    rng = np.random.default_rng(seed)
    truth = np.full((size, size), 0.02)
    for _ in range(n):
        y, x = rng.integers(20, size - 20, 2)
        truth[y, x] += rng.uniform(0.4, 1.0)
    output = np.zeros_like(truth)
    for x0 in range(0, size, 50):
        band = np.zeros_like(truth)
        band[:, x0:x0 + 50] = truth[:, x0:x0 + 50]
        sigma_x = 1.4 + 2.2 * (x0 / size)
        output += gaussian_filter1d(gaussian_filter1d(band, 1.4, axis=0), sigma_x, axis=1)
    output += rng.normal(0, 0.0008, output.shape)
    return Image(output[:, :, None].astype(np.float32))


# --- FWHMEccentricity -----------------------------------------------------------------

def test_the_field_map_recovers_the_injected_tilt():
    process = get("FWHMEccentricity")(fwhm=4.0, grid=3, max_stars=200)

    process.execute_on_image(tilted_field())
    result = process.result

    assert result["n_stars"] > 30
    left = [c for c in result["cells"] if c["col"] == 0 and c["fwhm"]]
    right = [c for c in result["cells"] if c["col"] == 2 and c["fwhm"]]
    assert left and right
    assert np.median([c["fwhm"] for c in right]) > np.median([c["fwhm"] for c in left])
    assert (np.median([c["eccentricity"] for c in right])
            > np.median([c["eccentricity"] for c in left]))


def test_the_grid_is_complete_even_where_there_is_no_star():
    """A hole in the map is information, not a cell to make disappear."""
    process = get("FWHMEccentricity")(fwhm=4.0, grid=4, max_stars=60)

    process.execute_on_image(tilted_field())

    assert len(process.result["cells"]) == 16
    assert all("n_stars" in c for c in process.result["cells"])


def test_an_empty_field_does_not_return_an_invented_measurement():
    rng = np.random.default_rng(0)
    flat = Image((np.full((128, 128, 1), 0.02) + rng.normal(0, 1e-4, (128, 128, 1)))
                 .astype(np.float32))

    process = get("FWHMEccentricity")(fwhm=3.0)
    process.execute_on_image(flat)

    assert process.result["n_stars"] == 0
    assert process.result["fwhm"] is None
    assert process.overlays() == []


def test_the_map_is_drawn_in_the_viewport():
    window = ImageWindow(tilted_field())

    get("FWHMEccentricity")(fwhm=4.0, grid=3, max_stars=150).execute_on(window.main_view)

    frames = [o for o in window.viewport.overlays if o.get("tag") == FIELD_MAP_TAG]
    assert {o["kind"] for o in frames} == {"ellipses", "text"}


def test_the_map_can_keep_quiet():
    window = ImageWindow(tilted_field())

    get("FWHMEccentricity")(fwhm=4.0, show_map=False).execute_on(window.main_view)

    assert not window.viewport.overlays


def test_the_measurement_does_not_touch_the_image():
    """A read-only process: no history entry, no modified pixel."""
    window = ImageWindow(tilted_field())
    before = window.main_view.image.data.copy()

    get("FWHMEccentricity")(fwhm=4.0, max_stars=50).execute_on(window.main_view)

    assert np.array_equal(window.main_view.image.data, before)


def test_the_moffat_profile_is_accepted():
    process = get("FWHMEccentricity")(fwhm=4.0, psf_model="moffat", max_stars=40, grid=2)

    process.execute_on_image(tilted_field())

    assert process.result["n_stars"] > 0
    assert all("beta" in e for e in process.result["stars"])


# --- AberrationInspector --------------------------------------------------------------

def test_the_mosaic_has_the_advertised_geometry():
    image = Image(np.zeros((400, 400, 3), dtype=np.float32))

    output = get("AberrationInspector")(mosaic_size=3, panel_size=64,
                                        separation=4).execute_on_image(image)

    assert output.data.shape == (3 * 64 + 2 * 4, 3 * 64 + 2 * 4, 3)


def test_the_corners_of_the_mosaic_are_the_corners_of_the_image():
    """Otherwise it does not show what it is asked to show."""
    data = np.zeros((200, 200, 1), dtype=np.float32)
    data[0:10, 0:10, 0] = 1.0        # top-left marker
    data[-10:, -10:, 0] = 0.5        # bottom-right marker

    output = get("AberrationInspector")(mosaic_size=3, panel_size=40,
                                        separation=2).execute_on_image(Image(data)).data

    assert output[0:10, 0:10, 0].max() == pytest.approx(1.0)
    assert output[-10:, -10:, 0].max() == pytest.approx(0.5)
    assert output[0:10, -10:, 0].max() == 0.0   # top-right corner of the image: empty


def test_a_thumbnail_larger_than_the_image_is_cropped():
    """Enlarging pixels would give the illusion of an optical defect."""
    image = Image(np.zeros((60, 60, 1), dtype=np.float32))

    output = get("AberrationInspector")(mosaic_size=3, panel_size=512,
                                        separation=0).execute_on_image(image)

    assert output.data.shape[0] <= 60


def test_the_mosaic_creates_a_window_without_touching_the_source():
    from retina.app import Application

    app = Application()
    window = app.new_window(Image(np.full((200, 200, 1), 0.3, dtype=np.float32)),
                             window_id="src")
    before = window.main_view.image.data.copy()

    app.apply(get("AberrationInspector")(mosaic_size=3, panel_size=32))

    assert len(app.windows) == 2
    assert np.array_equal(window.main_view.image.data, before)


# --- NoiseEvaluation ------------------------------------------------------------------

def noisy_field(sigma=0.003, density=2000, size=512):
    """A dense field: the case where a robust standard deviation measures structure, not noise."""
    from scipy.ndimage import gaussian_filter1d

    rng = np.random.default_rng(density)
    truth = np.zeros((size, size))
    for _ in range(density):
        y, x = rng.integers(5, size - 5, 2)
        truth[y, x] += rng.uniform(0.3, 1.5)
    blurred = gaussian_filter1d(gaussian_filter1d(truth, 1.6, axis=0), 1.6, axis=1)
    return Image((blurred + rng.normal(0, sigma, (size, size)))[:, :, None].astype(np.float32))


@pytest.mark.parametrize("sigma", [0.0005, 0.003, 0.02])
def test_pure_noise_is_recovered_over_three_orders_of_magnitude(sigma):
    from retina.noise_estimation import estimate_noise

    rng = np.random.default_rng(3)

    estimated = estimate_noise(rng.normal(0, sigma, (400, 400)))["sigma"]

    assert estimated == pytest.approx(sigma, rel=0.05)


def test_multiresolution_support_beats_a_robust_standard_deviation_on_a_dense_field():
    """This is the whole argument of the process: on this field a global MAD is 7 times too
    high."""
    from retina.noise_estimation import estimate_noise, noise_ksigma

    image = noisy_field(sigma=0.003, density=8000)
    plane = image.data[:, :, 0].astype(np.float64)

    mrs = estimate_noise(plane, method="mrs")
    ksigma, _ = noise_ksigma(plane)
    mad = 1.4826 * float(np.median(np.abs(plane - np.median(plane))))

    assert mrs["sigma"] == pytest.approx(0.003, rel=0.15)
    assert ksigma > 1.5 * mrs["sigma"]
    assert mad > 5 * mrs["sigma"]


def test_the_method_actually_used_is_returned():
    """Knowing that MRS did not converge matters as much as the figure itself."""
    from retina.noise_estimation import estimate_noise

    rng = np.random.default_rng(1)

    assert estimate_noise(rng.normal(0, 0.003, (256, 256)), method="ksigma")["method"] == "ksigma"
    assert estimate_noise(rng.normal(0, 0.003, (256, 256)), method="mrs")["method"] == "mrs"


def test_the_process_measures_every_channel():
    color = Image(np.stack([noisy_field(0.002).data[:, :, 0],
                              noisy_field(0.006).data[:, :, 0],
                              noisy_field(0.012).data[:, :, 0]], axis=2))

    process = get("NoiseEvaluation")()
    process.execute_on_image(color)

    sigmas = [c["sigma"] for c in process.result["channels"]]
    assert len(sigmas) == 3
    assert sigmas[0] < sigmas[1] < sigmas[2]
    assert sigmas[1] == pytest.approx(0.006, rel=0.2)


def test_cfa_mode_measures_the_four_subplanes():
    """A filter mixing two neighbouring Bayer sites would measure the mosaic, not the noise."""
    rng = np.random.default_rng(7)
    mosaic = rng.normal(0, 0.004, (256, 256))
    mosaic[0::2, 0::2] += 0.5      # one site markedly brighter than the others
    image = Image(mosaic[:, :, None].astype(np.float32))

    cfa = get("NoiseEvaluation")(cfa=True)
    cfa.execute_on_image(image)
    raw_data = get("NoiseEvaluation")(cfa=False)
    raw_data.execute_on_image(image)

    assert len(cfa.result["channels"]) == 4
    assert cfa.result["sigma"] == pytest.approx(0.004, rel=0.2)
    # Without CFA mode, the gap between sites enters the measurement. Multiresolution support
    # discards part of it — it marks the bright sites as significant — but not all of it: the
    # estimate still comes out 60 % too high.
    assert raw_data.result["sigma"] > 1.4 * cfa.result["sigma"]


def test_the_noise_measurement_does_not_touch_the_image():
    window = ImageWindow(noisy_field(density=200, size=200))
    before = window.main_view.image.data.copy()

    get("NoiseEvaluation")().execute_on(window.main_view)

    assert np.array_equal(window.main_view.image.data, before)
