"""Progress reporting and cancellation become real.

The infrastructure existed (``ProgressMonitor``, ``_progress``, ``job.progress``) but no
process was feeding it: the bar stayed indeterminate and "Cancel" interrupted nothing.
These tests pin down what is instrumented from now on — and what deliberately is not.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from retina.io.fits import save_fits
from retina.model.image import Image
from retina.process import context
from retina.process.progress import ProcessCancelled, ProgressMonitor, ScaledMonitor
from retina.process.registry import get


@pytest.fixture
def monitor():
    """Install a monitor for the duration of the test and yield (monitor, reports)."""
    reports: list[tuple[float | None, str]] = []
    m = ProgressMonitor()
    m.on_progress = lambda f, msg="": reports.append((f, msg))
    context.set_monitor(m)
    try:
        yield m, reports
    finally:
        context.set_monitor(None)


def frames(tmp_path, n=5):
    paths = []
    rng = np.random.default_rng(0)
    for i in range(n):
        p = str(tmp_path / f"f{i}.fits")
        save_fits(p, Image(rng.uniform(0.2, 0.3, (16, 16, 1)).astype(np.float32)))
        paths.append(p)
    return paths


# --- what is instrumented ------------------------------------------------------------

def test_integration_reports_frame_by_frame(monitor, tmp_path):
    _, reports = monitor
    get("Integration")(frames=frames(tmp_path, 5)).combine()

    reads = [m for f, m in reports if m.startswith("Reading")]
    assert len(reads) == 5
    assert reads[0].startswith("Reading 1/5")
    assert any("Integration" in m for _, m in reports)


def test_the_reported_fractions_never_decrease(monitor, tmp_path):
    _, reports = monitor
    get("Integration")(frames=frames(tmp_path, 4)).combine()

    fractions = [f for f, _ in reports if f is not None]
    assert fractions
    assert all(b >= a for a, b in itertools.pairwise(fractions))
    assert all(0.0 <= f <= 1.0 for f in fractions)


def test_the_measurements_report_frame_by_frame(monitor, tmp_path):
    _, reports = monitor
    get("SubframeSelector")(frames=frames(tmp_path, 3)).measure()

    assert [m for f, m in reports] == [
        "Measurement 1/3", "Measurement 2/3", "Measurement 3/3", "Measurements complete"]


def test_the_calibration_names_the_step_under_way(monitor, tmp_path):
    _, reports = monitor
    master = str(tmp_path / "m.fits")
    save_fits(master, Image(np.full((16, 16, 1), 0.1, dtype=np.float32)))

    get("ImageCalibration")(master_bias=master, master_dark=master).execute_on_image(
        Image(np.full((16, 16, 1), 0.5, dtype=np.float32)))

    messages = [m for _, m in reports]
    assert "Subtracting bias" in messages
    assert any(m.startswith("Subtracting dark") for m in messages)


def test_the_deconvolution_reports_per_channel(monitor):
    _, reports = monitor
    color = Image(np.full((16, 16, 3), 0.4, dtype=np.float32))

    get("Deconvolution")(iterations=2).execute_on_image(color)

    assert [m for _, m in reports if "channel" in m] == [
        f"Deconvolution — channel {c}/3" for c in (1, 2, 3)]


# --- what is not, and why -------------------------------------------------------------

def test_a_single_pass_process_stays_silent(monitor):
    """Instrumenting a tenth-of-a-second operation costs more than waiting for it."""
    _, reports = monitor
    get("Invert")().execute_on_image(Image(np.full((16, 16, 1), 0.4, dtype=np.float32)))

    assert reports == []


def test_without_an_installed_monitor_the_instrumentation_is_a_no_op(tmp_path):
    """The domain stays usable from a plain script, with no progress plumbing."""
    assert context.get_monitor() is None
    assert get("Integration")(frames=frames(tmp_path, 2)).combine().shape == (16, 16, 1)


# --- cancellation, which comes along for free ----------------------------------------

def test_cancelling_interrupts_an_integration_under_way(monitor, tmp_path):
    """`ProgressMonitor.report` is a checkpoint: instrumenting is enough."""
    m, reports = monitor
    m.on_progress = lambda f, msg="": (reports.append((f, msg)),
                                       m.cancel() if len(reports) >= 3 else None)

    with pytest.raises(ProcessCancelled):
        get("Integration")(frames=frames(tmp_path, 10)).combine()

    assert len(reports) < 10  # we did not run to the end


def test_cancelling_interrupts_the_measurements(monitor, tmp_path):
    m, reports = monitor
    m.on_progress = lambda f, msg="": (reports.append(msg),
                                       m.cancel() if len(reports) >= 2 else None)

    with pytest.raises(ProcessCancelled):
        get("SubframeSelector")(frames=frames(tmp_path, 8)).measure()


# --- ScaledMonitor: composing a pipeline's progress ----------------------------------

def test_the_scaled_monitor_maps_fractions_into_its_window():
    seen: list[float | None] = []
    parent = ProgressMonitor()
    parent.on_progress = lambda f, m="": seen.append(f)
    step = ScaledMonitor(parent, 0.25, 0.5)

    step.report(0.0)
    step.report(0.5)
    step.report(1.0)

    assert seen == [0.25, 0.5, 0.75]


def test_an_indeterminate_fraction_does_not_send_the_bar_backwards():
    seen: list[float | None] = []
    parent = ProgressMonitor()
    parent.on_progress = lambda f, m="": seen.append(f)
    step = ScaledMonitor(parent, 0.4, 0.2)

    step.report(None, "in progress")

    assert seen == [0.4]


def test_cancellation_passes_through_the_scaled_monitor():
    """The flag stays the parent's: cancelling from the interface reaches the step."""
    parent = ProgressMonitor()
    step = ScaledMonitor(parent, 0.0, 1.0)
    parent.cancel()

    assert step.cancelled
    with pytest.raises(ProcessCancelled):
        step.checkpoint()


def test_cancelling_the_step_cancels_the_parent():
    parent = ProgressMonitor()
    ScaledMonitor(parent, 0.0, 1.0).cancel()

    assert parent.cancelled


def test_out_of_range_fractions_are_brought_back_into_the_window():
    seen: list[float | None] = []
    parent = ProgressMonitor()
    parent.on_progress = lambda f, m="": seen.append(f)
    step = ScaledMonitor(parent, 0.5, 0.5)

    step.report(-1.0)
    step.report(2.0)

    assert seen == [0.5, 1.0]
