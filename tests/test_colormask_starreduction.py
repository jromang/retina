"""Hue mask and star reduction.

Both processes have a design flaw that is easy to make and only visible if you look for it: a
hue mask that does not close the circle misses **red**, the most requested colour; and a star
reduction by subtraction digs holes at the heart of bright stars. The tests below target those
two points.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.process import context
from retina.process.registry import get

pytest.importorskip("skimage")


def colour_patches(size=120):
    """Three flat patches of known hues on a dark grey background."""
    image = np.full((size, size, 3), 0.05, dtype=np.float32)
    image[10:40, 10:40] = (0.9, 0.1, 0.1)     # red, hue ≈ 0°
    image[10:40, 60:90] = (0.1, 0.9, 0.2)     # green, ≈ 130°
    image[60:90, 10:40] = (0.1, 0.2, 0.9)     # blue, ≈ 225°
    return Image(image)


# --- ColorMask ------------------------------------------------------------------------

@pytest.mark.parametrize("centre, sample", [
    (0.0, (20, 20)), (130.0, (20, 70)), (225.0, (70, 20)),
])
def test_each_hue_is_selected_exclusively(centre, sample):
    mask = get("ColorMask")(hue_center=centre, hue_width=25.0,
                              fuzziness=5.0).execute_on_image(colour_patches()).data

    y, x = sample
    others = [(20, 20), (20, 70), (70, 20)]
    others.remove(sample)
    assert mask[y, x, 0] == pytest.approx(1.0)
    assert all(mask[a, b, 0] == pytest.approx(0.0) for a, b in others)


def test_the_hue_closes_the_circle_on_red():
    """The trap: red sits at 0° *and* at 360°. A naive comparison selects neither."""
    image = np.full((40, 40, 3), 0.05, dtype=np.float32)
    image[10:30, 10:30] = (0.9, 0.12, 0.1)     # hue ≈ 1.5°, so astride the cut

    mask = get("ColorMask")(hue_center=355.0, hue_width=20.0,
                              fuzziness=0.0).execute_on_image(Image(image)).data

    assert mask[20, 20, 0] == pytest.approx(1.0)


def test_a_plain_grey_is_excluded_by_saturation():
    """On a grey pixel the hue is a rounding artefact: it can be anything at all."""
    rng = np.random.default_rng(0)
    gray = Image((np.full((60, 60, 3), 0.5) + rng.normal(0, 0.01, (60, 60, 3)))
                 .astype(np.float32))

    with_floor = get("ColorMask")(hue_center=0.0, hue_width=180.0,
                                  min_saturation=0.3).execute_on_image(gray).data
    without_floor = get("ColorMask")(hue_center=0.0, hue_width=180.0,
                                     min_saturation=0.0).execute_on_image(gray).data

    assert with_floor.mean() < 0.05
    assert without_floor.mean() > 0.9


def test_on_a_dark_background_lightness_protects_and_not_saturation():
    """The trap: HSV saturation is a *ratio*. A sky background at 0.06 with 0.01 of noise
    reports a saturation of 0.4 — as "colourful" as a plain flat patch."""
    rng = np.random.default_rng(0)
    background = Image((np.full((60, 60, 3), 0.06) + rng.normal(0, 0.01, (60, 60, 3)))
                 .astype(np.float32))

    by_saturation = get("ColorMask")(hue_center=0.0, hue_width=180.0,
                                     min_saturation=0.3).execute_on_image(background).data
    by_lightness = get("ColorMask")(hue_center=0.0, hue_width=180.0, min_saturation=0.3,
                                    min_lightness=0.2).execute_on_image(background).data

    assert by_saturation.mean() > 0.2      # saturation is not enough
    assert by_lightness.mean() == 0.0      # lightness is


def test_fuzziness_softens_the_edge_of_the_range():
    image = np.full((40, 40, 3), 0.05, dtype=np.float32)
    image[10:30, 10:30] = (0.9, 0.55, 0.1)     # hue ≈ 34°, outside the crisp range

    crisp = get("ColorMask")(hue_center=0.0, hue_width=20.0,
                             fuzziness=0.0).execute_on_image(Image(image)).data
    blurred = get("ColorMask")(hue_center=0.0, hue_width=20.0,
                            fuzziness=30.0).execute_on_image(Image(image)).data

    assert crisp[20, 20, 0] == pytest.approx(0.0)
    assert 0.0 < blurred[20, 20, 0] < 1.0


def test_the_mask_creates_a_single_channel_window():
    from retina.app import Application

    app = Application()
    app.new_window(colour_patches(), window_id="src")

    app.apply(get("ColorMask")(hue_center=0.0))

    assert len(app.windows) == 2
    assert app.windows[-1].main_view.image.data.shape[2] == 1


def test_a_mono_image_is_refused():
    with pytest.raises(ValueError, match="color"):
        get("ColorMask")().execute_on_image(Image(np.zeros((16, 16, 1), dtype=np.float32)))


# --- StarReduction --------------------------------------------------------------------

def field_and_starless(size=200, seed=2):
    """A gentle background and stars, combined by the **screen model** — hence separable."""
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(seed)
    peaks = np.zeros((size, size))
    positions = []
    for _ in range(30):
        y, x = rng.integers(15, size - 15, 2)
        peaks[y, x] += rng.uniform(1.5, 3.0)
        positions.append((y, x))
    stars = np.clip(gaussian_filter(peaks, 2.0), 0.0, 1.0)
    background = np.clip(0.15 + 0.05 * gaussian_filter(rng.normal(0, 1, (size, size)), 12), 0, 1)
    combine = 1.0 - (1.0 - background) * (1.0 - stars)
    three = lambda p: np.repeat(p[:, :, None], 3, axis=2).astype(np.float32)  # noqa: E731
    return Image(three(combine)), Image(three(background)), positions


@pytest.fixture
def injected_starless():
    image, without, positions = field_and_starless()
    context.set_image_provider(lambda i: without if i == "less" else None)
    try:
        yield image, without, positions
    finally:
        context.set_image_provider(None)


def test_transfer_damps_the_stars_and_leaves_the_background(injected_starless):
    image, _, positions = injected_starless

    output = get("StarReduction")(method="transfer", starless="less",
                                  strength=0.6).execute_on_image(image).data

    y, x = positions[0]
    assert output[y, x, 0] < image.data[y, x, 0]
    # The background must come back to itself: that is what the screen model guarantees.
    background = image.data[:, :, 0] < 0.25
    assert np.abs(output[:, :, 0] - image.data[:, :, 0])[background].mean() < 0.002


def test_transfer_does_not_dig_a_hole_at_the_heart_of_the_stars(injected_starless):
    """A subtraction would leave black craters where the image saturates."""
    image, _, positions = injected_starless

    output = get("StarReduction")(method="transfer", starless="less",
                                  strength=1.0).execute_on_image(image).data

    for y, x in positions[:10]:
        assert output[y, x, 0] >= image.data[y, x, 0] * 0.4 - 1e-6
    assert output.min() >= 0.0


def test_strength_doses_the_reduction(injected_starless):
    image, _, positions = injected_starless
    y, x = positions[0]

    gentle = get("StarReduction")(method="transfer", starless="less",
                                  strength=0.2).execute_on_image(image).data
    strong = get("StarReduction")(method="transfer", starless="less",
                                  strength=0.9).execute_on_image(image).data

    assert strong[y, x, 0] < gentle[y, x, 0] < image.data[y, x, 0]


def test_the_morphological_method_does_without_a_starless():
    """That is its point: available right away, without removing the stars first."""
    image, _, positions = field_and_starless()

    output = get("StarReduction")(method="morphological",
                                  strength=1.0, iterations=2).execute_on_image(image).data

    y, x = positions[0]
    assert output[y, x, 0] < image.data[y, x, 0]


@pytest.mark.parametrize("method", ["transfer", "halo"])
def test_without_a_starless_view_the_process_says_what_to_do(method):
    image, _, _ = field_and_starless(size=64)

    with pytest.raises(ValueError, match="starless"):
        get("StarReduction")(method=method).execute_on_image(image)


def test_a_starless_of_different_geometry_is_refused():
    image, _, _ = field_and_starless(size=64)
    context.set_image_provider(
        lambda i: Image(np.zeros((32, 32, 3), dtype=np.float32)) if i == "less" else None)
    try:
        with pytest.raises(ValueError, match="same geometry"):
            get("StarReduction")(method="transfer", starless="less").execute_on_image(image)
    finally:
        context.set_image_provider(None)


def test_a_zero_strength_changes_nothing(injected_starless):
    image, _, _ = injected_starless

    output = get("StarReduction")(method="transfer", starless="less",
                                  strength=0.0).execute_on_image(image).data

    assert np.array_equal(output, image.data)
