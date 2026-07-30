"""MultiscaleGradientCorrection against an external reference.

Without a reference, the process takes *everything* large-scale for gradient: extended
nebulosity leaves along with the light pollution. Given an image of the same field free of
gradient, it can tell the difference — and it can do so even when the reference is neither
linear nor photometric, which a DSS plate is not.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Image
from retina.io.fits import save_fits
from retina.processes.gradient import MultiscaleGradientCorrection

N = 192
SCALE = 5


def _field():
    """Returns (gradient-free sky, gradient, observed image)."""
    ys, xs = np.mgrid[0:N, 0:N].astype(np.float64)
    r2 = (xs - N / 2) ** 2 + (ys - N / 2) ** 2
    bubble = 0.20 * np.exp(-r2 / (2 * (N / 5) ** 2))  # extended nebulosity
    sky = 0.05 + bubble
    gradient = 0.15 * (xs / (N - 1))  # light pollution, as a ramp
    rng = np.random.default_rng(7)
    observed = sky + gradient + rng.normal(0.0, 0.001, (N, N))
    return sky, gradient, observed


def _contrast(plane: np.ndarray) -> float:
    """Gap between the core of the nebulosity and the corners — its large-scale signature."""
    ys, xs = np.mgrid[0:N, 0:N]
    r2 = (xs - N / 2) ** 2 + (ys - N / 2) ** 2
    core = r2 < (N / 10) ** 2
    corners = r2 > (N / 2.2) ** 2
    return float(plane[core].mean() - plane[corners].mean())


def _dss_reference(tmp_path, sky):
    """Photographic-plate-style reference: same shape, **non-linear** response."""
    plate = (sky / sky.max()) ** 0.6
    path = tmp_path / "reference.fits"
    save_fits(str(path), Image(plate[:, :, None].astype(np.float32)))
    return str(path)


def test_without_a_reference_the_nebulosity_leaves_with_the_gradient():
    """The earlier behaviour — useful, but blind. This is the baseline."""
    sky, _gradient, observed = _field()
    proc = MultiscaleGradientCorrection(scale=SCALE, pedestal=0.1)

    output = proc.execute_on_image(Image(observed[:, :, None].astype(np.float32)))

    # The nebulosity is clearly there in the ground truth (contrast 0.181) and only a fifth
    # of it remains after correction (0.040): four fifths of the extended signal were taken
    # for gradient, and removed along with it.
    assert _contrast(sky) > 0.15
    assert _contrast(output.data[:, :, 0]) < 0.3 * _contrast(sky)


def test_with_a_reference_the_nebulosity_survives_and_the_gradient_leaves(tmp_path):
    """The discriminating test: this is the whole point of the feature."""
    sky, _gradient, observed = _field()
    proc = MultiscaleGradientCorrection(
        scale=SCALE, pedestal=0.1, reference_path=_dss_reference(tmp_path, sky)
    )

    plane = proc.execute_on_image(Image(observed[:, :, None].astype(np.float32))).data[:, :, 0]

    # the nebulosity is restored…
    assert _contrast(plane) == pytest.approx(_contrast(sky), rel=0.15)
    # …and the ramp is gone: the background of the left and right edges meets again. Before
    # correction, the two are separated by the 0.15 of the gradient.
    edge = N // 12
    left = float(np.median(plane[:, :edge]))
    right = float(np.median(plane[:, -edge:]))
    assert abs(left - right) < 0.02
    assert abs(np.median(observed[:, :edge]) - np.median(observed[:, -edge:])) > 0.10


def test_a_flat_reference_cannot_explain_anything(tmp_path):
    """Documented fallback: without structure, the reference is discarded rather than used."""
    _sky, _gradient, observed = _field()
    path = tmp_path / "flat.fits"
    save_fits(str(path), Image(np.full((N, N, 1), 0.3, np.float32)))
    proc = MultiscaleGradientCorrection(scale=SCALE, pedestal=0.1, reference_path=str(path))
    bare = MultiscaleGradientCorrection(scale=SCALE, pedestal=0.1)

    image = Image(observed[:, :, None].astype(np.float32))
    np.testing.assert_allclose(
        proc.execute_on_image(image).data, bare.execute_on_image(image).data, atol=1e-6
    )


def test_a_reference_of_a_different_geometry_is_resampled(tmp_path):
    """The nominal case: the reference is requested downsampled, and the real-time preview
    itself works on a decimated image."""
    sky, _gradient, observed = _field()
    small = sky[::3, ::3]
    path = tmp_path / "small.fits"
    save_fits(str(path), Image((small / small.max())[:, :, None].astype(np.float32)))
    proc = MultiscaleGradientCorrection(scale=SCALE, pedestal=0.1, reference_path=str(path))

    plane = proc.execute_on_image(Image(observed[:, :, None].astype(np.float32))).data[:, :, 0]

    assert _contrast(plane) == pytest.approx(_contrast(sky), rel=0.15)


def test_a_missing_reference_raises(tmp_path):
    """Repository rule: a reference that is asked for and absent is an error, never a no-op."""
    _sky, _gradient, observed = _field()
    proc = MultiscaleGradientCorrection(scale=SCALE, reference="nonexistent_view")

    with pytest.raises(ValueError):
        proc.execute_on_image(Image(observed[:, :, None].astype(np.float32)))


def test_without_a_reference_the_result_is_the_historical_one():
    """Non-regression guard, computed by hand from the starlet transform."""
    from retina.processes.multiscale import starlet_transform

    _sky, _gradient, observed = _field()
    plane = observed.astype(np.float32)
    details, residual = starlet_transform(plane, SCALE)
    expected = np.clip(sum(details) + np.median(residual) + 0.1, 0.0, 1.0).astype(np.float32)

    actual = MultiscaleGradientCorrection(scale=SCALE, pedestal=0.1).execute_on_image(
        Image(plane[:, :, None])
    )

    np.testing.assert_array_equal(actual.data[:, :, 0], expected)
