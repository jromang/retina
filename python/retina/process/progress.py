"""Process progress and cooperative cancellation — with no shell dependency.

A worker (GUI or script) installs a :class:`ProgressMonitor` through
``process.context.set_monitor`` (*thread-local* storage: one worker = one thread = one
monitor, no leakage between concurrent executions). Processes instrument their loops with
``self._progress(fraction, message)`` and ``self._checkpoint()`` — a no-op without a monitor,
so nothing is mandatory for the existing processes.

Cancellation is cooperative: ``monitor.cancel()`` (thread-safe, a plain flag) makes
:class:`ProcessCancelled` raise at the next checkpoint; ``execute_on`` then discards the
history bracket (``View.abort_process``) — the view is not modified.
"""

from __future__ import annotations

from collections.abc import Callable


class ProcessCancelled(Exception):
    """Raised by :meth:`ProgressMonitor.checkpoint` when cancellation has been requested."""


class ProgressMonitor:
    def __init__(self) -> None:
        self._cancelled = False
        #: callback ``(fraction: float | None, message: str)`` — ``None`` = indeterminate.
        #: On the shell side, rebroadcast from the loop (never touch the UI from the worker).
        self.on_progress: Callable[[float | None, str], None] | None = None

    def report(self, fraction: float | None, message: str = "") -> None:
        """Report progress — and serve as a natural cancellation point."""
        if self.on_progress is not None:
            self.on_progress(fraction, message)
        self.checkpoint()

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def checkpoint(self) -> None:
        """Call inside long loops: raises if cancellation has been requested."""
        if self._cancelled:
            raise ProcessCancelled()


class ScaledMonitor(ProgressMonitor):
    """The ``[offset, offset+scale]`` window of a parent monitor.

    A job has only one monitor, but a pipeline chains dozens of steps, each of which reports
    its own progress from 0 to 1. Wrapping a step's execution in a ``ScaledMonitor`` rescales
    its fractions to the global bar: the step believes it runs from 0 to 1, the parent sees
    the portion that belongs to it.

    Nothing else changes — instrumented processes call ``self._progress`` without knowing who
    listens, and cancellation passes through since the flag remains the parent's.
    """

    def __init__(self, parent: ProgressMonitor, offset: float, scale: float) -> None:
        super().__init__()
        self._parent = parent
        self._offset = float(offset)
        self._scale = float(scale)

    def report(self, fraction: float | None, message: str = "") -> None:
        if fraction is None:
            # indeterminate progress: keep the position already reached rather than clear
            # the bar, but keep passing the message up.
            self._parent.report(self._offset, message)
        else:
            bound = min(max(float(fraction), 0.0), 1.0)
            self._parent.report(self._offset + self._scale * bound, message)

    def cancel(self) -> None:
        self._parent.cancel()

    @property
    def cancelled(self) -> bool:
        return self._parent.cancelled

    def checkpoint(self) -> None:
        self._parent.checkpoint()
