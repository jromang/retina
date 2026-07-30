"""GeneralizedHyperbolicStretch.

The equations come from the published reference documentation of the GHS module; what is
checked here are the **properties** a tone curve must have whatever happens: monotonic,
bounded, continuous at its joins, and exactly invertible. A formula copied out crookedly breaks
at least one of the four, including when it looks plausible to the eye.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.process.registry import get
from retina.processes.stretch import ghs_transfer

#: one point per sub-family of the equation — these are five different formulas
FAMILIES = [
    pytest.param(-1.0, id="logarithmic"),
    pytest.param(-3.0, id="integral"),
    pytest.param(0.0, id="exponential"),
    pytest.param(1.0, id="harmonic"),
    pytest.param(8.0, id="hyperbolic"),
]

X = np.linspace(0.0, 1.0, 2001)


def curve(b, *, sf=3.0, sp=0.15, lp=0.0, hp=1.0, inverse=False):
    return ghs_transfer(X, sf, b, sp, lp, hp, inverse=inverse)


@pytest.mark.parametrize("b", FAMILIES)
def test_the_curve_is_monotonic_and_runs_from_zero_to_one(b):
    y = curve(b)

    assert np.all(np.diff(y) >= -1e-12)
    assert y[0] == pytest.approx(0.0, abs=1e-9)
    assert y[-1] == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("b", FAMILIES)
def test_the_round_trip_through_the_inverse_form_is_exact(b):
    y = curve(b, sp=0.15, lp=0.05, hp=0.85)

    back = ghs_transfer(y, 3.0, b, 0.15, 0.05, 0.85, inverse=True)

    assert np.abs(back - X).max() < 1e-9


def test_a_zero_factor_is_the_identity():
    """`D = 0` is not a degenerate case to avoid: it is the slider at rest."""
    assert np.allclose(curve(7.0, sf=0.0), X, atol=1e-12)


@pytest.mark.parametrize("switch", [-1.0, 0.0, 1.0])
def test_the_curve_does_not_jump_at_the_formula_switchovers(switch):
    """At b = −1, 0 and 1 the equation changes form. The curve must not.

    The trap is real: the sub-families are not on the same scale (T'(0) is 1 for the integral
    and D for the others). It is the normalisation that makes up the difference — and this test
    is what verifies it.
    """
    before, exact, after = (curve(switch + d) for d in (-1e-4, 0.0, 1e-4))

    assert np.abs(exact - before).max() < 1e-3
    assert np.abs(after - exact).max() < 1e-3


def test_the_protections_join_straight_segments():
    lp, hp = 0.08, 0.88
    y = curve(6.0, sf=2.5, sp=0.2, lp=lp, hp=hp)
    slope = np.diff(y) / np.diff(X)

    # Below LP and above HP, the transformation is linear by construction.
    below = slope[X[:-1] < lp - 0.005]
    above = slope[X[:-1] > hp + 0.005]
    assert below.std() < 1e-9
    assert above.std() < 1e-9
    # …and the join is made along the tangent: no break of slope at either junction.
    for bound in (lp, hp):
        i = int(bound * 2000)
        assert slope[i - 3] == pytest.approx(slope[i + 3], rel=0.05)


def test_the_symmetry_point_is_indeed_the_slope_maximum():
    """This is the whole point of GHS over a HistogramTransformation: you choose *where* the
    contrast is spent."""
    sp = 0.3
    y = curve(10.0, sf=3.0, sp=sp, lp=0.0, hp=1.0)
    slope = np.diff(y) / np.diff(X)

    assert X[int(np.argmax(slope))] == pytest.approx(sp, abs=0.01)


def test_inconsistent_bounds_are_clamped_instead_of_raising():
    """An SP slider crossing LP must not make the preview fail on every image."""
    y = ghs_transfer(X, 3.0, 5.0, 0.2, lp=0.9, hp=0.05)

    assert np.all(np.isfinite(y))
    assert np.all(np.diff(y) >= -1e-12)


# --- the process ----------------------------------------------------------------------

def color_field(h=32, w=32):
    base = np.linspace(0.0, 0.5, h * w).reshape(h, w).astype(np.float32)
    return Image(np.stack([base, base * 0.6, base * 0.3], axis=2))


def test_the_process_brightens_and_stays_within_bounds():
    image = color_field()

    output = get("GeneralizedHyperbolicStretch")(
        stretch_factor=3.0, local_intensity=5.0, symmetry_point=0.1).execute_on_image(image)

    assert output.data.min() >= 0.0 and output.data.max() <= 1.0
    assert output.data.mean() > image.data.mean()


def test_colour_mode_preserves_the_ratios_between_channels():
    """This is what RGB mode does not do: stretching the channels separately brings them
    together, and so washes the image out."""
    image = color_field()
    kw = {"stretch_factor": 2.0, "local_intensity": 4.0, "symmetry_point": 0.1}

    color = get("GeneralizedHyperbolicStretch")(mode="colour", **kw).execute_on_image(image)
    rgb = get("GeneralizedHyperbolicStretch")(mode="rgb", **kw).execute_on_image(image)

    # The mask is the one from the original image, applied to all three: recomputing it on each
    # output would not compare the same pixels — a stretch lets more of them through.
    kept = image.data[:, :, 0].ravel() > 0.05

    def deviation(d):
        return d[:, :, 1].ravel()[kept] / np.maximum(d[:, :, 0].ravel()[kept], 1e-6)

    origin = deviation(image.data)
    assert np.allclose(deviation(color.data), origin, atol=1e-3)
    # RGB mode, for its part, really does bring the channels together — the flaw we document.
    assert np.abs(deviation(rgb.data) - origin).max() > 0.05


def test_lightness_mode_does_not_touch_the_chrominance():
    pytest.importorskip("skimage")
    from skimage.color import rgb2lab

    image = color_field()

    output = get("GeneralizedHyperbolicStretch")(
        mode="lightness", stretch_factor=2.0, local_intensity=4.0,
        symmetry_point=0.1).execute_on_image(image)

    before, after = rgb2lab(np.clip(image.data, 0, 1)), rgb2lab(np.clip(output.data, 0, 1))
    assert np.abs(after[:, :, 1:] - before[:, :, 1:]).max() < 1.0
    assert after[:, :, 0].mean() > before[:, :, 0].mean()


def test_the_process_has_a_realtime_preview():
    """Nothing to wire up: `supports_realtime` is true by default, and GHS is precisely the
    process you tune while watching the image."""
    assert get("GeneralizedHyperbolicStretch").realtime_capable()


def test_the_python_echo_replays_the_setting():
    source = get("GeneralizedHyperbolicStretch")(
        stretch_factor=2.5, local_intensity=6.0, invert=True).to_python_source()

    assert "stretch_factor=2.5" in source
    assert "invert=True" in source
