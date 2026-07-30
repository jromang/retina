"""CPU/GPU parity against the **real** CuPy — skipped anywhere there is no card.

The fake cupy of `test_gpu_dispatch.py` checks the wiring; here we check the numbers, which
only a real GPU can do. These tests are therefore absent from CI and present on the
development machine, which is the intended division.

**Bit-for-bit is not promised, and cannot be**: a GPU FFT does not sum in the same order as a
CPU FFT. The tolerances below are measured, not guessed.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("cupy")

from retina.backend import xp

pytestmark = pytest.mark.gpu

if not xp.gpu_available():  # CuPy installed but no card visible
    pytest.skip("no GPU available", allow_module_level=True)


@pytest.fixture(autouse=True)
def without_ambient_kill_switch(monkeypatch):
    """A machine-wide ``RETINA_GPU=0`` would prevent every upload, hence every test here.

    The tests that *are about* the kill switch set it themselves; the others must be able to
    count on a neutral environment, just as the suite pins the language.
    """
    monkeypatch.delenv("RETINA_GPU", raising=False)


@pytest.fixture
def field():
    """A blurred, noisy star field — enough to give the deconvolution something to chew on."""
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(3)
    img = np.full((256, 256), 0.02, np.float32)
    for _ in range(30):
        iy, ix = rng.integers(20, 236, 2)
        img[iy, ix] += 1.0
    blurred = gaussian_filter(img, 2.0).astype(np.float32)
    return (blurred + rng.normal(0, 0.001, blurred.shape).astype(np.float32)).astype(np.float32)


@pytest.fixture
def psf():
    y, x = np.mgrid[-7:8, -7:8]
    kernel = np.exp(-(x * x + y * y) / 8.0)
    return (kernel / kernel.sum()).astype(np.float32)


def _on_gpu(arr):
    uploaded = xp.to_device(arr, min_pixels=0)
    assert xp._is_cupy(uploaded), "the array should have moved to the GPU"
    return uploaded


# --- Richardson-Lucy ---------------------------------------------------------------------

def test_bare_rl_is_identical_down_to_floating_point_epsilon(field, psf):
    from retina.backend.deconvolve import richardson_lucy

    cpu = richardson_lucy(field, psf, 30)
    gpu = xp.to_numpy(richardson_lucy(_on_gpu(field), _on_gpu(psf), 30))

    np.testing.assert_allclose(gpu, cpu, atol=1e-5, rtol=0)


def test_regularised_rl_diverges_on_only_a_handful_of_pixels(field, psf):
    """Hard thresholding is **discontinuous**: a coefficient sitting right on the threshold
    falls on one side or the other according to a floating-point difference, and thirty
    iterations amplify the branching. This is not a porting mistake, it is the nature of the
    regulariser — so what we require is that the difference stay rare and that the flux
    itself be preserved."""
    from retina.backend.deconvolve import richardson_lucy

    cpu = richardson_lucy(field, psf, 30, regularization=3.0)
    gpu = xp.to_numpy(richardson_lucy(_on_gpu(field), _on_gpu(psf), 30, regularization=3.0))

    deviation = np.abs(gpu - cpu)
    assert float(np.median(deviation)) < 1e-6
    assert float((deviation > 1e-4).mean()) < 0.005  # fewer than one pixel in two hundred
    assert float(abs(gpu.sum() - cpu.sum()) / cpu.sum()) < 1e-5  # the flux itself is preserved


def test_the_deconvolution_process_gives_the_same_result_with_or_without_gpu(
    field, psf, monkeypatch
):
    """The full path, the way a user triggers it."""
    from retina import Image
    from retina.processes.restore import Deconvolution

    proc = Deconvolution(iterations=15, psf_mode="parametric", psf_sigma=2.0)
    image = Image(field[:, :, None])

    monkeypatch.setenv("RETINA_GPU", "0")
    on_host = proc.execute_on_image(image).data
    monkeypatch.delenv("RETINA_GPU")
    monkeypatch.setattr(xp, "GPU_MIN_PIXELS", 0)  # the test field is small
    on_gpu = proc.execute_on_image(image).data

    np.testing.assert_allclose(on_gpu, on_host, atol=1e-4, rtol=0)


# --- total variation ----------------------------------------------------------------------

def test_tv_chambolle_is_identical_on_gpu(field):
    from retina.backend.denoise import tv_chambolle

    cpu = tv_chambolle(field, 0.05)
    gpu = xp.to_numpy(tv_chambolle(_on_gpu(field), 0.05))

    np.testing.assert_allclose(gpu, cpu, atol=1e-5, rtol=0)


def test_multichannel_tv_is_identical_on_gpu(field):
    from retina.backend.denoise import tv_chambolle

    color = np.stack([field, field * 0.8, field * 1.2], axis=-1).astype(np.float32)
    cpu = tv_chambolle(color, 0.05, channel_axis=-1)
    gpu = xp.to_numpy(tv_chambolle(_on_gpu(color), 0.05, channel_axis=-1))

    np.testing.assert_allclose(gpu, cpu, atol=1e-5, rtol=0)


# --- TGV -----------------------------------------------------------------------------------

def test_tgv_on_gpu_is_bit_for_bit_the_rust_result(field):
    """Same operations, same order, float64: here parity is *exact*, with no tolerance.

    It is possible because the TGV loop has neither reduction nor FFT — only element-wise
    ufuncs, which do not depend on the summation order."""
    from retina.processes.denoise import _tgv_denoise_channel

    plane = field.astype(np.float64)
    rust = _tgv_denoise_channel(plane, 0.1, 0.2, 60)
    gpu = xp.to_numpy(_tgv_denoise_channel(_on_gpu(plane), 0.1, 0.2, 60))

    np.testing.assert_array_equal(gpu, rust)


def test_the_tgv_process_gives_the_same_result_with_or_without_gpu(field, monkeypatch):
    from retina import Image
    from retina.processes.denoise import TGVDenoise

    proc = TGVDenoise(strength=0.1, iterations=40)
    image = Image(field[:, :, None])

    monkeypatch.setenv("RETINA_GPU", "0")
    on_host = proc.execute_on_image(image).data
    monkeypatch.delenv("RETINA_GPU")
    monkeypatch.setattr(xp, "GPU_MIN_PIXELS", 0)
    on_gpu = proc.execute_on_image(image).data

    np.testing.assert_array_equal(on_gpu, on_host)


# --- kill switch, with a real CuPy array --------------------------------------------------

def test_a_real_cupy_array_comes_back_down_under_the_kill_switch(field, monkeypatch):
    """The exact scenario of the trap that was fixed, played against the real CuPy."""
    uploaded = _on_gpu(field)
    monkeypatch.setenv("RETINA_GPU", "0")

    assert xp.is_gpu(uploaded) is False
    brought_back = xp.to_numpy(uploaded)  # must not raise
    assert isinstance(brought_back, np.ndarray) and not xp._is_cupy(brought_back)
    np.testing.assert_array_equal(brought_back, field)
    assert xp.to_device(field, min_pixels=0) is field  # and nothing moves up any more
