"""Reference-grade deconvolution.

Three things are checked here, in this order: that the Richardson-Lucy loop written in-house
**reproduces** the reference implementation (without which the rewrite would be a disguised
regression), that regularisation **earns what it claims** (the background noise stays stable
where bare RL amplifies it), and that the three PSF sources really do end up with the
announced kernel.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.backend.deconvolve import richardson_lucy
from retina.model.image import Image
from retina.process import context
from retina.process.progress import ProcessCancelled, ProgressMonitor
from retina.process.registry import get
from retina.processes.psf import (
    _median_angle,
    median_psf_image,
    psf_kernel,
)

pytest.importorskip("photutils")


def gaussian_kernel(sigma: float) -> np.ndarray:
    r = max(1, int(np.ceil(3 * sigma)))
    ax = np.arange(-r, r + 1, dtype=np.float64)
    g = np.exp(-(ax**2) / (2 * sigma**2))
    k = np.outer(g, g)
    return k / k.sum()


def field(size=140, sigma_x=2.0, sigma_y=2.0, n=30, noise=0.002, seed=5):
    """A field of point stars blurred by a known gaussian, plus noise."""
    from scipy.ndimage import gaussian_filter1d

    rng = np.random.default_rng(seed)
    truth = np.full((size, size), 0.02)
    positions = []
    for _ in range(n):
        y, x = rng.integers(20, size - 20, 2)
        positions.append((int(y), int(x)))
        truth[y, x] += rng.uniform(0.4, 1.0)
    blurred = gaussian_filter1d(gaussian_filter1d(truth, sigma_y, axis=0), sigma_x, axis=1)
    return blurred + rng.normal(0, noise, blurred.shape), truth, positions


def color(plan: np.ndarray, channels: int = 3) -> Image:
    return Image(np.repeat(plan[:, :, None], channels, axis=2).astype(np.float32))


# --- the loop -------------------------------------------------------------------------

def test_our_richardson_lucy_reproduces_the_reference_implementation():
    """At the core of the image, to the twelfth decimal. At the edges we do *something else*
    — reflection versus a zero border — and that is deliberate (see the next test)."""
    sk = pytest.importorskip("skimage.restoration")
    obs, _, _ = field(size=96, sigma_x=1.5, sigma_y=1.5, n=20, noise=0.0)
    psf = gaussian_kernel(1.0)

    ours = richardson_lucy(obs, psf, 8)
    theirs = sk.richardson_lucy(obs, psf, num_iter=8, clip=False)

    core = (slice(32, 64), slice(32, 64))
    assert np.abs(ours[core] - theirs[core]).max() < 1e-9


def test_the_edges_do_not_take_the_dark_fringe_of_a_zero_border():
    """An image of constant level must stay that way: which is what a zero border fails to do."""
    flat = np.full((64, 64), 0.3)
    output = richardson_lucy(flat, gaussian_kernel(2.0), 30)

    assert output.min() > 0.29
    assert abs(float(output.mean()) - 0.3) < 1e-3


def test_regularisation_holds_the_background_noise_that_bare_rl_amplifies():
    """The very argument for the regulariser: iterate long without the background blowing up."""
    obs, _, _ = field(size=128, sigma_x=2.0, sigma_y=2.0, noise=0.003, seed=3)
    psf = gaussian_kernel(2.0)
    background = (slice(0, 20), slice(0, 20))

    bare = richardson_lucy(obs, psf, 200)
    regularised = richardson_lucy(obs, psf, 200, regularization=3.0)

    assert bare[background].std() > 3 * regularised[background].std()
    # …without giving up on restoring, either: the peak stays well above the observation.
    assert regularised.max() > 1.3 * obs.max()


def test_the_psf_is_normalised_so_flux_is_preserved():
    obs, _, _ = field(size=96, n=15, noise=0.0)
    raw = gaussian_kernel(1.5) * 17.0  # sum ≠ 1: must be normalised without complaint

    output = richardson_lucy(obs, raw, 20)

    assert abs(output.sum() / obs.sum() - 1.0) < 0.01


def test_on_iteration_counts_the_rounds_and_can_interrupt_them():
    obs, _, _ = field(size=64, n=8, noise=0.0)
    psf = gaussian_kernel(1.0)

    rounds: list[int] = []
    richardson_lucy(obs, psf, 6, on_iteration=rounds.append)
    assert rounds == [1, 2, 3, 4, 5, 6]

    class Halt(Exception):
        pass

    def cut(i):
        if i == 3:
            raise Halt

    with pytest.raises(Halt):
        richardson_lucy(obs, psf, 500, on_iteration=cut)


@pytest.mark.parametrize("psf, pattern", [
    (np.zeros((5, 5)), "null or negative sum"),
    (np.ones(5) / 5, "2D"),
])
def test_an_unusable_psf_raises_rather_than_returning_noise(psf, pattern):
    with pytest.raises(ValueError, match=pattern):
        richardson_lucy(np.full((16, 16), 0.2), psf, 2)


def test_an_even_sided_kernel_is_accepted():
    """It has no central pixel; we pad it rather than refusing to run."""
    output = richardson_lucy(np.full((32, 32), 0.2), np.ones((4, 4)) / 16.0, 3)
    assert output.shape == (32, 32)


def test_the_float_type_of_the_input_is_preserved():
    obs = np.full((32, 32), 0.2)
    assert richardson_lucy(obs.astype(np.float32), gaussian_kernel(1.0), 2).dtype == np.float32
    assert richardson_lucy(obs, gaussian_kernel(1.0), 2).dtype == np.float64


# --- the measured PSF -----------------------------------------------------------------

def test_the_measured_psf_recovers_the_widths_that_did_the_blurring():
    obs, _, _ = field(size=200, sigma_x=2.0, sigma_y=1.2, n=40, noise=0.0005, seed=7)

    kernel = median_psf_image(obs, fwhm_guess=4.0)

    assert kernel is not None
    assert kernel.shape[0] % 2 == 1 and kernel.shape[0] == kernel.shape[1]
    assert abs(float(kernel.sum()) - 1.0) < 1e-5
    yy, xx = np.mgrid[0:kernel.shape[0], 0:kernel.shape[1]]
    centre = (kernel.shape[0] - 1) / 2
    sx = float(np.sqrt((kernel * (xx - centre) ** 2).sum()))
    sy = float(np.sqrt((kernel * (yy - centre) ** 2).sum()))
    assert sx == pytest.approx(2.0, abs=0.2)
    assert sy == pytest.approx(1.2, abs=0.2)


def test_a_starless_field_does_not_return_a_psf_of_noise():
    rng = np.random.default_rng(0)
    flat = np.full((64, 64), 0.02) + rng.normal(0, 1e-4, (64, 64))

    assert median_psf_image(flat, fwhm_guess=3.0) is None


def test_the_measured_psf_can_also_fit_a_moffat():
    obs, _, _ = field(size=180, sigma_x=1.8, sigma_y=1.8, n=35, noise=0.0005, seed=11)

    assert median_psf_image(obs, function="moffat", fwhm_guess=4.0) is not None


def test_the_orientation_median_closes_the_circle():
    """+89° and −89° point in almost the same direction; their naive mean, in the normal one."""
    angles = np.radians(np.array([89.0, -89.0, 88.0, -88.0]))

    assert abs(np.degrees(_median_angle(angles))) == pytest.approx(89.0, abs=1.5)


def test_psf_kernel_returns_a_normalised_elliptical_kernel():
    kernel = psf_kernel(fwhm_x=6.0, fwhm_y=2.0)

    assert abs(float(kernel.sum()) - 1.0) < 1e-5
    # `x_fwhm` is the width along the columns (the convention of `_psf_model`, evaluated at
    # (x, y)): the horizontal cut therefore carries more flux than the vertical one.
    assert kernel[kernel.shape[0] // 2, :].sum() > 2 * kernel[:, kernel.shape[1] // 2].sum()


# --- the process ----------------------------------------------------------------------

def test_an_old_process_icon_replays_as_is():
    """The only two parameters that predate the rework keep their id, type and default: an
    instance serialised before the redesign reads back without migration."""
    old = {"process_id": "Deconvolution", "values": {"psf_sigma": 2.0, "iterations": 20}}

    instance = get("Deconvolution").from_dict(old)

    assert instance.psf_sigma == 2.0
    assert instance.iterations == 20
    assert instance.psf_mode == "parametric"  # the default reproduces the earlier behaviour


def test_deconvolution_tightens_the_stars():
    obs, _, positions = field(size=120, sigma_x=2.0, sigma_y=2.0, n=20, seed=13)
    image = color(obs)

    output = get("Deconvolution")(psf_sigma=2.0, iterations=30).execute_on_image(image)

    y, x = positions[0]
    assert output.data[y, x, 0] > image.data[y, x, 0]


def test_the_measured_psf_is_properly_wired_into_the_process():
    """The `measured` mode must actually *measure*: on an anisotropic field it does better
    than an isotropic gaussian of badly chosen width."""
    obs, _, positions = field(size=160, sigma_x=2.6, sigma_y=1.2, n=30, seed=17)
    image = color(obs, channels=1)

    measure = get("Deconvolution")(psf_mode="measured", psf_sigma=1.5,
                                  iterations=40).execute_on_image(image)
    isotropic = get("Deconvolution")(psf_sigma=1.5, iterations=40).execute_on_image(image)

    peaks = [(measure.data[y, x, 0], isotropic.data[y, x, 0]) for y, x in positions]
    assert np.median([m for m, _ in peaks]) > np.median([i for _, i in peaks])


def test_a_view_can_stand_in_as_the_psf():
    obs, _, _ = field(size=100, n=15, seed=19)
    kernel = psf_kernel(fwhm_x=4.0)
    context.set_image_provider(
        lambda i: Image(kernel[:, :, None].astype(np.float32)) if i == "psf1" else None)
    try:
        output = get("Deconvolution")(psf_mode="external", psf_view="psf1",
                                      iterations=10).execute_on_image(color(obs))
    finally:
        context.set_image_provider(None)

    assert output.data.shape == (100, 100, 3)
    assert np.isfinite(output.data).all()


@pytest.mark.parametrize("values, pattern", [
    ({"psf_mode": "external"}, "psf_view"),
    ({"psf_mode": "external", "psf_view": "missing"}, "not found"),
    ({"psf_mode": "measured"}, "not enough"),
])
def test_a_psf_that_cannot_be_resolved_says_so(values, pattern):
    flat = Image(np.full((48, 48, 1), 0.3, dtype=np.float32))

    with pytest.raises(ValueError, match=pattern):
        get("Deconvolution")(**values, iterations=3).execute_on_image(flat)


def test_deringing_reduces_the_trough_around_the_stars():
    obs, _, positions = field(size=120, sigma_x=2.0, sigma_y=2.0, n=20, seed=23)
    image = color(obs, channels=1)
    y, x = positions[0]
    ring = (slice(y - 6, y + 7), slice(x - 6, x + 7))

    raw = get("Deconvolution")(psf_sigma=2.6, iterations=60).execute_on_image(image)
    softened = get("Deconvolution")(psf_sigma=2.6, iterations=60, dering_dark=1.0,
                                    dering_bright=0.5).execute_on_image(image)

    assert softened.data[ring].min() > raw.data[ring].min()


def test_star_protection_pulls_the_input_back_on_the_stars():
    obs, _, positions = field(size=120, sigma_x=2.0, sigma_y=2.0, n=20, seed=29)
    image = color(obs, channels=1)

    protected = get("Deconvolution")(psf_sigma=2.0, iterations=40,
                                     star_protection=1.0).execute_on_image(image)
    free = get("Deconvolution")(psf_sigma=2.0, iterations=40).execute_on_image(image)

    y, x = positions[0]
    assert abs(protected.data[y, x, 0] - obs[y, x]) < abs(free.data[y, x, 0] - obs[y, x])


def test_luminance_mode_preserves_the_colour_ratios():
    obs, _, _ = field(size=96, n=15, seed=31)
    hue = np.stack([obs * 1.0, obs * 0.7, obs * 0.4], axis=2).astype(np.float32)

    output = get("Deconvolution")(psf_sigma=2.0, iterations=20,
                                  luminance_only=True).execute_on_image(Image(hue))

    core = (slice(20, 76), slice(20, 76))
    before = hue[core][..., 1] / np.maximum(hue[core][..., 0], 1e-6)
    after = output.data[core][..., 1] / np.maximum(output.data[core][..., 0], 1e-6)
    assert np.allclose(before, after, atol=1e-4)


# --- progress and cancellation --------------------------------------------------------

def test_progress_now_reaches_all_the_way_down_to_the_iteration():
    reports: list[tuple[float | None, str]] = []
    monitor = ProgressMonitor()
    monitor.on_progress = lambda f, msg="": reports.append((f, msg))
    context.set_monitor(monitor)
    try:
        get("Deconvolution")(psf_sigma=1.5, iterations=10).execute_on_image(
            Image(np.full((32, 32, 1), 0.3, dtype=np.float32)))
    finally:
        context.set_monitor(None)

    iterations = [m for _, m in reports if "iteration" in m]
    assert iterations, "no per-iteration report"
    assert iterations[-1] == "Deconvolution — iteration 10/10"
    # The frozen instrumentation test counts the messages containing "channel": the
    # per-iteration reports must not slip in among them.
    assert not any("channel" in m for m in iterations)
    fractions = [f for f, _ in reports if f is not None]
    assert fractions == sorted(fractions)
    assert fractions[0] >= 0.0 and fractions[-1] <= 1.0


def test_cancellation_is_honoured_from_the_next_iteration_on():
    monitor = ProgressMonitor()
    seen: list[int] = []

    def watch(fraction, message=""):
        seen.append(len(seen))
        if len(seen) == 2:
            monitor.cancel()

    monitor.on_progress = watch
    context.set_monitor(monitor)
    try:
        with pytest.raises(ProcessCancelled):
            get("Deconvolution")(psf_sigma=1.5, iterations=400).execute_on_image(
                Image(np.full((48, 48, 1), 0.3, dtype=np.float32)))
    finally:
        context.set_monitor(None)

    # Interrupted well before the 400 rounds: cancellation no longer waits for a channel to end.
    assert len(seen) < 20
