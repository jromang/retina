"""Progress / cooperative cancellation — headless, without the shell."""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.model.view import View
from retina.process import context
from retina.process.base import Process
from retina.process.progress import ProcessCancelled, ProgressMonitor


class _Slow(Process):
    process_id = "SlowTest"
    parameters = []

    def _apply(self, data):
        for i in range(4):
            self._progress(i / 4, f"step {i}")
        return data * 2.0


def test_monitor_report_and_cancel() -> None:
    monitor = ProgressMonitor()
    got: list[tuple[float | None, str]] = []
    monitor.on_progress = lambda f, msg: got.append((f, msg))
    monitor.report(0.5, "x")
    assert got == [(0.5, "x")]
    assert not monitor.cancelled
    monitor.cancel()
    with pytest.raises(ProcessCancelled):
        monitor.checkpoint()


def test_process_reports_via_thread_local_monitor() -> None:
    monitor = ProgressMonitor()
    fractions: list[float | None] = []
    monitor.on_progress = lambda f, msg: fractions.append(f)
    context.set_monitor(monitor)
    try:
        view = View(Image(np.ones((4, 4, 1), dtype=np.float32)))
        assert _Slow().execute_on(view)
        assert fractions == [0.0, 0.25, 0.5, 0.75]
        assert view.history_index == 1
    finally:
        context.set_monitor(None)


def test_cancel_aborts_without_touching_history() -> None:
    monitor = ProgressMonitor()
    context.set_monitor(monitor)
    try:
        view = View(Image(np.ones((4, 4, 1), dtype=np.float32)))
        before = view.image
        monitor.cancel()
        with pytest.raises(ProcessCancelled):
            _Slow().execute_on(view)
        assert view.history_index == 0
        assert len(view._history) == 1
        assert view.image is before
        # the bracket is purged: a following process runs normally
        monitor2 = ProgressMonitor()
        context.set_monitor(monitor2)
        assert _Slow().execute_on(view)
        assert view.history_index == 1
    finally:
        context.set_monitor(None)


def test_no_monitor_is_noop_and_headless() -> None:
    view = View(Image(np.ones((4, 4, 1), dtype=np.float32)))
    assert _Slow().execute_on(view)
    # The absence of the shell can no longer be asserted here: `tests/server/` loads aiohttp
    # into the same process. The real guarantee lives in tests/server/test_headless_parity.py,
    # which starts a fresh interpreter.
