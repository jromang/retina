"""The xp dispatch: upload policy, kill-switch, and the GPU branches without a GPU.

These tests run everywhere, including in CI without a card: the fake cupy of `fake_cupy.py`
is enough to exercise the wiring. Numerical correctness, for its part, is checked against the
real CuPy in `test_gpu_parity.py`.
"""

from __future__ import annotations

import numpy as np
import pytest
import scipy.fft
import scipy.ndimage
from fake_cupy import install
from retina.backend import xp


@pytest.fixture
def fake_gpu(monkeypatch):
    """Install the fake cupy, and **reset the availability cache on the way out**."""
    module = install(monkeypatch)
    yield module
    xp.reset_availability()


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    """No test may inherit another one's availability verdict.

    We also drop an ambient ``RETINA_GPU``: each test sets the kill-switch itself when that is
    its subject. Without this, the suite would pass or not depending on the workstation's
    environment — the same trap as the language, pinned for the same reason.
    """
    monkeypatch.delenv("RETINA_GPU", raising=False)
    xp.reset_availability()
    yield
    xp.reset_availability()


# --- the default behaviour, with nothing special -----------------------------------------

def test_numpy_by_default():
    arr = np.zeros((4, 4), np.float32)
    assert xp.get_array_module(arr) is np
    assert xp.is_gpu(arr) is False
    assert xp.ndimage_for(arr) is scipy.ndimage
    assert xp.fft_for(arr) is scipy.fft
    np.testing.assert_array_equal(xp.to_numpy(arr), arr)


def test_without_cupy_to_device_returns_the_input(monkeypatch):
    monkeypatch.setattr(xp, "gpu_available", lambda: False)
    arr = np.zeros((2000, 2000), np.float32)
    assert xp.to_device(arr) is arr


# --- the upload policy ------------------------------------------------------------------

def test_to_device_uploads_a_large_image(fake_gpu):
    arr = np.zeros((1200, 1200), np.float32)  # > GPU_MIN_PIXELS
    uploaded = xp.to_device(arr)
    assert xp._is_cupy(uploaded)
    assert xp.get_array_module(uploaded).__name__ == "cupy"


def test_a_small_image_stays_on_the_host(fake_gpu):
    """The real-time preview loops over small previews: uploading them would cost more than
    the computation itself."""
    arr = np.zeros((64, 64), np.float32)
    assert xp.to_device(arr) is arr


def test_the_threshold_is_adjustable(fake_gpu):
    arr = np.zeros((64, 64), np.float32)
    assert xp._is_cupy(xp.to_device(arr, min_pixels=0))


def test_an_array_already_on_the_gpu_is_not_uploaded_again(fake_gpu):
    uploaded = xp.to_device(np.zeros((1200, 1200), np.float32))
    assert xp.to_device(uploaded) is uploaded


def test_a_failed_upload_falls_back_to_the_host(fake_gpu):
    """Out of memory right at upload, context lost: slow but correct, never an exception."""
    def refuse(*a, **k):
        raise RuntimeError("out of memory")

    fake_gpu.asarray = refuse
    arr = np.zeros((1200, 1200), np.float32)
    assert xp.to_device(arr) is arr


# --- the kill-switch, and the trap it used to hide ---------------------------------------

def test_retina_gpu_0_prevents_the_upload(fake_gpu, monkeypatch):
    monkeypatch.setenv("RETINA_GPU", "0")
    arr = np.zeros((1200, 1200), np.float32)
    assert xp.to_device(arr) is arr


def test_the_preference_prevents_the_upload(fake_gpu, monkeypatch):
    monkeypatch.setattr(xp, "gpu_disabled", lambda: True)
    arr = np.zeros((1200, 1200), np.float32)
    assert xp.to_device(arr) is arr


def test_a_gpu_array_stays_usable_under_the_kill_switch(fake_gpu, monkeypatch):
    """The trap this fixed: `is_gpu` conflated type and policy, so that a genuine CuPy array
    under `RETINA_GPU=0` routed to numpy — and `np.pad` raised."""
    uploaded = xp.to_device(np.zeros((1200, 1200), np.float32))
    monkeypatch.setenv("RETINA_GPU", "0")

    assert xp.is_gpu(uploaded) is False          # the *policy* says no…
    assert xp._is_cupy(uploaded) is True         # …but the *type* does not change
    assert xp.get_array_module(uploaded).__name__ == "cupy"
    assert isinstance(xp.to_numpy(uploaded), np.ndarray)  # and it comes back down anyway


def test_gpu_available_is_cached_then_forgettable(fake_gpu):
    assert xp.gpu_available() is True
    xp.reset_availability()
    assert xp.gpu_available() is True


def test_without_a_device_gpu_available_says_no(monkeypatch):
    install(monkeypatch, available=False)
    xp.reset_availability()
    assert xp.gpu_available() is False


# --- OOM recognition and fallback --------------------------------------------------------

def test_oom_is_recognised_by_its_name():
    from fake_cupy import OutOfMemoryError

    assert xp.is_oom(OutOfMemoryError("full"))
    assert not xp.is_oom(ValueError("something else"))
    assert not xp.is_oom(MemoryError("host, not GPU"))


def test_freeing_memory_calls_the_pool(fake_gpu):
    from fake_cupy import POOL

    before = POOL.frees
    xp.free_gpu_memory()
    assert POOL.frees == before + 1


def test_synchronize_never_raises(fake_gpu):
    xp.synchronize()  # must do nothing visible, and above all not raise


# --- the matching modules ----------------------------------------------------------------

def test_the_matching_modules_follow_the_type(fake_gpu):
    uploaded = xp.to_device(np.zeros((1200, 1200), np.float32))
    assert xp.ndimage_for(uploaded).__name__ == "cupyx.scipy.ndimage"
    assert xp.fft_for(uploaded).__name__ == "cupyx.scipy.fft"
    assert xp.get_array_module(np.zeros(4), uploaded).__name__ == "cupy"  # one is enough
