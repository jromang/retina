"""Narrowband emission-line injection and SHO normalisation.

The test field carries a **known scale**: the narrow band is acquired with a 2× gain and a
lower background than the broadband channel. Recovering that 2× is the whole problem, and it
is where two plausible approaches fail — the module's documentation says which ones and why.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.process import context
from retina.process.registry import get
from retina.processes.narrowband import background_pixels, scale_from_stars

pytest.importorskip("photutils")

GAIN_NB = 2.0        # the narrow band is twice as sensitive
BACKGROUND_RGB = 0.10
BACKGROUND_NB = 0.02


def field(size=200, seed=5):
    """Nebula plus stars, seen through a broad band and a narrow band."""
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    nebula = 0.6 * np.exp(-(((xx - size / 2) / 25.0) ** 2
                            + ((yy - size / 2) / 18.0) ** 2))
    peaks = np.zeros((size, size))
    for _ in range(25):
        y, x = rng.integers(10, size - 10, 2)
        peaks[y, x] += 1.2
    stars = gaussian_filter(peaks, 1.8)
    noise = lambda: rng.normal(0, 0.002, (size, size))  # noqa: E731

    red = BACKGROUND_RGB + 0.06 * nebula + stars + noise()
    rgb = np.stack([red, BACKGROUND_RGB + stars + noise(),
                    BACKGROUND_RGB + stars + noise()], axis=2)
    ha = np.clip(BACKGROUND_NB + GAIN_NB * (nebula + stars) + noise(), 0.0, 1.0)
    center = (size // 2, size // 2)
    star_peak = np.unravel_index(int(np.argmax(stars)), stars.shape)
    return (Image(np.clip(rgb, 0, 1).astype(np.float32)),
            Image(ha[:, :, None].astype(np.float32)), center, star_peak)


@pytest.fixture
def scene():
    rgb, ha, center, star = field()
    context.set_image_provider(lambda i: ha if i == "ha" else None)
    try:
        yield rgb, ha, center, star
    finally:
        context.set_image_provider(None)


# --- the scale ------------------------------------------------------------------------

def test_the_scale_is_recovered_despite_the_stars_sitting_on_the_nebula():
    """This is the heart of the problem: those stars have an aberrant ratio, and a pixel-by-pixel
    regression latches onto it. The median of the per-star ratios does not."""
    rgb, ha, _, _ = field()

    factor = scale_from_stars(ha.data[:, :, 0].astype(np.float64),
                                  rgb.data[:, :, 0].astype(np.float64))

    assert factor == pytest.approx(1.0 / GAIN_NB, rel=0.1)


def test_without_enough_stars_the_scale_gives_up_rather_than_inventing():
    rng = np.random.default_rng(0)
    flat = np.full((128, 128), 0.1) + rng.normal(0, 1e-4, (128, 128))

    assert scale_from_stars(flat, flat) is None


def test_the_background_pixels_exclude_what_is_significant_everywhere():
    rgb, ha, center, star = field()
    planes = [rgb.data[:, :, 0].astype(np.float64), ha.data[:, :, 0].astype(np.float64)]

    background = background_pixels(planes)

    assert 0.1 < background.mean() < 0.95
    assert not background[center]            # the nebula is not background
    assert not background[star]              # nor is a star


# --- NBRGBCombination -----------------------------------------------------------------

def test_the_emission_line_is_injected_in_proportion_to_the_strength(scene):
    rgb, _, center, _ = scene
    before = float(rgb.data[center][0])

    soft = get("NBRGBCombination")(ha_view="ha", strength=0.3).execute_on_image(rgb).data
    strong = get("NBRGBCombination")(ha_view="ha", strength=0.8).execute_on_image(rgb).data

    assert before < soft[center][0] < strong[center][0]


def test_stars_are_not_counted_twice(scene):
    """We inject the **excess** and not the image: a star that is bright in both does not stand
    out, and so is not added a second time."""
    rgb, _, _, star = scene
    before = float(rgb.data[star][0])

    output = get("NBRGBCombination")(ha_view="ha", strength=0.8).execute_on_image(rgb).data

    assert output[star][0] == pytest.approx(before, rel=0.05)


def test_the_sky_background_is_not_lifted(scene):
    """The offset is keyed on the background, precisely for this."""
    rgb, _, _, _ = scene
    corner = (slice(0, 20), slice(0, 20))

    output = get("NBRGBCombination")(ha_view="ha", strength=0.8).execute_on_image(rgb).data

    assert output[corner][:, :, 0].mean() == pytest.approx(
        rgb.data[corner][:, :, 0].mean(), abs=0.005)


def test_only_the_targeted_channel_is_touched(scene):
    rgb, _, _, _ = scene

    output = get("NBRGBCombination")(ha_view="ha", ha_channel="red",
                                     strength=0.8).execute_on_image(rgb).data

    assert np.array_equal(output[:, :, 1], rgb.data[:, :, 1])
    assert np.array_equal(output[:, :, 2], rgb.data[:, :, 2])


def test_a_zero_strength_is_the_identity(scene):
    rgb, _, _, _ = scene

    output = get("NBRGBCombination")(ha_view="ha", strength=0.0).execute_on_image(rgb).data

    assert np.allclose(output, rgb.data, atol=1e-6)


def test_bandwidth_mode_injects_less(scene):
    """Physically grounded, but discreet: a 7/100 ratio gives 7 % of the excess."""
    rgb, _, center, _ = scene

    manual = get("NBRGBCombination")(ha_view="ha", mode="manual",
                                     strength=1.0).execute_on_image(rgb).data
    band = get("NBRGBCombination")(ha_view="ha", mode="bandwidth", strength=1.0,
                                    nb_bandwidth=7.0,
                                    rgb_bandwidth=100.0).execute_on_image(rgb).data

    assert band[center][0] < manual[center][0]


def test_with_no_emission_line_the_process_says_what_to_do():
    rgb, _, _, _ = field(size=64)

    with pytest.raises(ValueError, match="no emission line"):
        get("NBRGBCombination")().execute_on_image(rgb)


def test_an_emission_line_of_a_different_geometry_is_refused():
    rgb, _, _, _ = field(size=64)
    context.set_image_provider(
        lambda i: Image(np.zeros((32, 32, 1), dtype=np.float32)) if i == "ha" else None)
    try:
        with pytest.raises(ValueError, match="same geometry"):
            get("NBRGBCombination")(ha_view="ha").execute_on_image(rgb)
    finally:
        context.set_image_provider(None)


# --- NarrowbandNormalization ----------------------------------------------------------

def sho(size=200, backgrounds=(0.30, 0.05, 0.60), noise=0.002, seed=3):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    nebula = 0.5 * np.exp(-(((xx - size / 2) / 25.0) ** 2
                            + ((yy - size / 2) / 18.0) ** 2))
    planes = [b + nebula + rng.normal(0, noise, (size, size)) for b in backgrounds]
    return Image(np.clip(np.stack(planes, axis=2), 0, 1).astype(np.float32))


def test_the_backgrounds_are_aligned_on_the_reference_channel():
    image = sho()
    corner = (slice(0, 30), slice(0, 30))

    output = get("NarrowbandNormalization")(reference="green").execute_on_image(image).data

    backgrounds = [output[corner][:, :, c].mean() for c in range(3)]
    assert backgrounds[0] == pytest.approx(backgrounds[1], abs=0.01)
    assert backgrounds[2] == pytest.approx(backgrounds[1], abs=0.01)


def test_the_emission_is_not_erased_by_the_normalisation():
    """Aligning over the whole image would amount to erasing what we are trying to show."""
    image = sho()
    center = (100, 100)

    output = get("NarrowbandNormalization")(reference="green").execute_on_image(image).data

    for c in range(3):
        contrast = output[center][c] - output[0:30, 0:30, c].mean()
        assert contrast > 0.3


def test_a_perfectly_flat_background_does_not_disable_the_process():
    """Degenerate case: the line is undefined, but the offset is not. Doing nothing would give
    a process that appears to run without acting."""
    image = sho(noise=0.0)
    corner = (slice(0, 30), slice(0, 30))

    output = get("NarrowbandNormalization")(reference="green").execute_on_image(image).data

    backgrounds = [output[corner][:, :, c].mean() for c in range(3)]
    assert backgrounds[0] == pytest.approx(backgrounds[1], abs=0.01)
    assert backgrounds[2] == pytest.approx(backgrounds[1], abs=0.01)


def test_offset_only_mode_does_not_touch_the_contrast():
    image = sho()
    corner = (slice(0, 30), slice(0, 30))
    center = (100, 100)
    contrast_before = image.data[center][2] - image.data[corner][:, :, 2].mean()

    output = get("NarrowbandNormalization")(reference="green",
                                            match_scale=False).execute_on_image(image).data

    assert (output[center][2] - output[corner][:, :, 2].mean()) == pytest.approx(
        contrast_before, rel=0.02)


def test_all_three_views_or_none():
    image = sho(size=64)

    with pytest.raises(ValueError, match="all three views"):
        get("NarrowbandNormalization")(red_view="r").execute_on_image(image)


def test_a_mono_image_without_views_is_refused():
    with pytest.raises(ValueError, match="3-channel"):
        get("NarrowbandNormalization")().execute_on_image(
            Image(np.zeros((32, 32, 1), dtype=np.float32)))
