"""Running processes in the background.

The worker never touches the UI: it publishes WebSocket notifications. The rule is the
same — **a worker never touches the interface** — and so is the invariant that makes it
hold: the :class:`ProgressMonitor` is installed *thread-locally* for the duration of the
run, through ``process.context.set_monitor``.

# What is instrumented, and what is not

The **long** processes (integration, measurements, registration, calibration, deconvolution,
denoising, background extraction) call ``self._progress()`` in their loops: their bar is
determinate and "Cancel" interrupts them mid-course, since ``ProgressMonitor.report`` acts as
a checkpoint. The others — the hundred or so operations that run in a single numpy pass —
stay mute: their fraction is ``None`` (indeterminate bar) and cancellation only takes effect
when they end. That is deliberate: instrumenting a tenth-of-a-second operation would cost
more than waiting for it.

The fraction is **stored on the job** in addition to being notified: without that, a client
reconnecting mid-run would find an empty bar.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable
from concurrent.futures import Executor, Future
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..process import context
from ..process.progress import ProcessCancelled, ProgressMonitor

if TYPE_CHECKING:
    from ..app import Application

log = logging.getLogger("retina.server")

_counter = itertools.count(1)


def _result_of(item: Any) -> dict | None:
    """Result of a measurement process, if it publishes one.

    The inspection processes (``DynamicPSF``, ``Statistics``, ``RadialProfileMeasurement``)
    deposit a dictionary in ``self.result``: it is their only output, since they do not touch
    the pixels. The job only picked it up on the ``call`` path (the pipeline), so that a
    measurement process launched from a form **never returned anything to the client** — the
    interface had no way to display what it had measured.
    """
    result = getattr(item, "result", None)
    return result if isinstance(result, dict) else None


@dataclass
class Job:
    """One process run, from submission to result."""

    id: str
    process_id: str
    view: str | None
    state: str = "queued"  # queued | running | done | error | cancelled
    message: str = ""
    #: last progress reported — ``None`` = indeterminate
    fraction: float | None = None
    #: last step label reported ("Measurement 12/40")
    progress_message: str = ""
    #: payload returned by a ``call`` job (a pipeline report). Published with the final
    #: notification, never in the snapshot — ``active()`` only lists jobs in flight, which
    #: do not have a result yet.
    result: dict | None = None
    monitor: ProgressMonitor = field(default_factory=ProgressMonitor)
    future: Future | None = None
    #: work to run when it is not a process (the pipeline, for instance).
    #: A callable rather than a fake process: a registered process would require bilingual
    #: documentation and an icon, for an operation that is not one.
    call: Callable[[], object] | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "process_id": self.process_id,
            "view": self.view,
            "state": self.state,
            "message": self.message,
            "fraction": self.fraction,
            "progress_message": self.progress_message,
            "result": self.result,
        }


class JobRunner:
    """Queue of runs, backed by the server's thread pool."""

    def __init__(
        self,
        app: Application,
        executor: Executor,
        notify: Callable[[str, dict], None],
        on_finished: Callable[[], None],
    ) -> None:
        self._app = app
        self._executor = executor
        self._notify = notify
        self._on_finished = on_finished
        self._jobs: dict[str, Job] = {}

    # --- state ----------------------------------------------------------------
    def active(self) -> list[dict]:
        """Jobs still in flight — that is what the snapshot publishes."""
        return [job.to_dict() for job in self._jobs.values() if job.state in ("queued", "running")]

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def needs_active_view(self) -> bool:
        """True if no view is active — a non-global process would have no target.

        The refusal happens here rather than in the worker: an immediate RPC error is better
        than a job that starts only to fail a second later.
        """
        return self._app.active_view is None

    # --- submission -----------------------------------------------------------
    def submit(self, item: Any, process_id: str, view: str | None) -> str:
        job = Job(id=f"j{next(_counter)}", process_id=process_id, view=view)
        self._jobs[job.id] = job
        # `on_progress` is called from the worker thread: `notify` republishes onto the
        # loop — the equivalent of a queued connection. We store it on the way, so that the
        # snapshot carries the progress and a reconnection finds it again.
        job.monitor.on_progress = self._progress_hook(job)
        job.future = self._executor.submit(self._run, job, item)
        return job.id

    def submit_call(self, fn: Callable[[], object], label: str) -> str:
        """Submit work that is not a process — same queue, same cancellation.

        The pipeline is its only client: it orchestrates processes rather than being one. It
        thereby inherits progress, cooperative cancellation and publication in the snapshot,
        without duplicating anything.
        """
        job = Job(id=f"j{next(_counter)}", process_id=label, view=None, call=fn)
        self._jobs[job.id] = job
        job.monitor.on_progress = self._progress_hook(job)
        job.future = self._executor.submit(self._run, job, None)
        return job.id

    def has_active(self, process_id: str) -> bool:
        """True if a job of that name is already queued or running."""
        return any(j.process_id == process_id and j.state in ("queued", "running")
                   for j in self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        """Cooperative cancellation. See the limit documented at the top of the module."""
        job = self._jobs.get(job_id)
        if job is None or job.state in ("done", "error", "cancelled"):
            return False
        job.monitor.cancel()
        # Not started yet: we can pull it out of the queue for good.
        if job.future is not None and job.future.cancel():
            self._finish(job, "cancelled")
        return True

    def _progress_hook(self, job: Job) -> Callable[[float | None, str], None]:
        def progression(fraction: float | None, message: str = "") -> None:
            job.fraction = fraction
            job.progress_message = message
            self._notify("job.progress",
                         {"job": job.id, "fraction": fraction, "message": message})

        return progression

    # --- execution ------------------------------------------------------------
    def _run(self, job: Job, item: Any) -> None:
        context.set_monitor(job.monitor)
        try:
            if job.monitor.cancelled:  # cancelled before it even started
                self._finish(job, "cancelled")
                return
            job.state = "running"
            self._notify("job.started", job.to_dict())

            if job.call is not None:
                result = job.call()
                job.result = result if isinstance(result, dict) else None
                ok = result is not False
            elif job.view is not None:
                ok = self._app.apply(item, view=self._app.view(job.view))
                job.result = _result_of(item)
            else:
                # `run` dispatches: global process → execute_global, otherwise → active view
                ok = self._app.run(item)
                job.result = _result_of(item)
            self._finish(job, "done" if ok else "error",
                         "" if ok else "the process returned a failure")
        except ProcessCancelled:
            self._finish(job, "cancelled")
        except Exception as exc:
            log.exception("job %s (%s) failed", job.id, job.process_id)
            self._finish(job, "error", f"{type(exc).__name__}: {exc}")
        finally:
            context.set_monitor(None)

    def _finish(self, job: Job, state: str, message: str = "") -> None:
        job.state = state
        job.message = message
        job.fraction = 1.0 if state == "done" else None
        # A job error becomes a durable domain state: the `job.error` notification alone
        # evaporates client-side as soon as the progress bar fades. Neither `done` nor
        # `cancelled` leave one — that would be noise.
        if state == "error":
            self._app.notifications.add(message, kind="error", source=job.process_id)
        self._notify(f"job.{state}", job.to_dict())
        # The snapshot will follow: a process may have changed pixels, history, windows.
        self._on_finished()
