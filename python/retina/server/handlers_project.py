"""``project.*`` family — save and reopen a complete session.

Like every handler family, this one contains **no logic**: it transports, guards against the
accident, and delegates to ``app.save_project`` / ``app.open_project`` — which do the work and
emit the Python echo.

# The documents blob, and why it must be *asked for*

A project must carry what the domain does not know about: the open script tabs with their
unsaved buffers, the recipes being written, the console transcript. These states live on the
client side, and that is the right place — an editor tab is chrome, not a domain action (a
design choice we do not undo here).

The mechanism is that of the **perspectives**, generalized: the server pushes a
``project.command {op: "request_documents"}`` notification, the client answers with the
``project.store_documents`` RPC. One sizeable difference, however: ``save_perspective`` is
fire-and-forget, whereas here the blob is needed *before* writing the file. Hence the
correlation by ``request`` and the bounded wait below — a wait that takes place in the **job
thread**, never on the asyncio loop, which must stay free to receive the answer.

Three cases, and none of them must make the save fail:

* a client answers → its blob goes into the file;
* no client connected (headless, CLI, cron) → we rewrite the blob the session already carries,
  without asking anyone;
* a connected client that does not answer (frozen page, suspended tab) → after the timeout, we
  write with what we have. A project without its tabs is better than a project not written.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from .rpc import DOMAIN_ERROR, RpcError

if TYPE_CHECKING:
    from ..app import Application
    from .broadcast import Broadcaster
    from .jobs import JobRunner

#: Names under which the two operations appear in the job list.
SAVE_JOB = "SaveProject"
OPEN_JOB = "OpenProject"

#: Wait timeout for the documents blob. Short on purpose: this is a local serialization of a
#: few kilobytes, not a network round trip. Beyond that, the client will not answer.
DEFAULT_REQUEST_TIMEOUT = 2.0

PROJECT_METHODS: dict[str, bool] = {  # {RPC name: mutating}
    # `save` does not mutate the domain (it writes it) but updates the current project, which
    # the snapshot publishes — the job takes care of that at its end (`on_finished`).
    "project.save": False,
    # `open` replaces every window: mutating, no discussion.
    "project.open": True,
    "project.close": True,
    # The client's answer to `request_documents`, or a spontaneous deposit. This is a
    # **report**, not a user action: no echo, exactly like `layout.store_perspective`.
    "project.store_documents": False,
    "project.recent": False,
    "project.set_reopen": True,
    # The language is a session preference, filed with the recents and the reopen flag —
    # hence its place here rather than in a family of its own. Mutating: the client re-reads
    # its session state, and reloads if the effective language has changed.
    "project.set_language": True,
}


class ProjectService:
    """Correlates document requests between the loop and the job thread."""

    def __init__(self, app: Application, broadcast: Broadcaster,
                 timeout: float = DEFAULT_REQUEST_TIMEOUT) -> None:
        self._app = app
        self._broadcast = broadcast
        self._timeout = float(timeout)
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Event] = {}
        self._answers: dict[str, Any] = {}
        self._counter = 0

    def request_documents(self) -> object | None:
        """Asks the client for its blob and waits for it — **from the job thread**.

        Returns the session's blob if nobody answers: it is the last one known, and
        overwriting it with ``None`` would make the user lose their tabs for the sole reason
        that their page did not answer in time.
        """
        if self._broadcast.client_count == 0:
            return self._app.project_documents()
        with self._lock:
            self._counter += 1
            request = f"d{self._counter}"
            event_ = threading.Event()
            self._pending[request] = event_
        self._broadcast.notify("project.command",
                               {"op": "request_documents", "request": request})
        received = event_.wait(self._timeout)
        with self._lock:
            self._pending.pop(request, None)
            response = self._answers.pop(request, None)
        return response if received else self._app.project_documents()

    def deliver(self, request: str, documents: Any) -> None:
        """The client's answer — called from the loop, wakes the job thread."""
        with self._lock:
            event_ = self._pending.get(request)
            if event_ is None:
                return
            self._answers[request] = documents
        event_.set()


class ProjectHandlers:
    def __init__(self, app: Application, runner: JobRunner, service: ProjectService) -> None:
        self._app = app
        self._runner = runner
        self._service = service

    # --- guards ----------------------------------------------------------------
    def _resolve(self, path: str) -> str:
        """Absolute path, suffix completed. Same anti-accident guard as ``fs.*``: a relative
        path would be resolved against the server's current directory, which makes no sense
        for the client."""
        from pathlib import Path

        from ..io.project import PROJECT_SUFFIX

        if not isinstance(path, str) or not path:
            raise RpcError(DOMAIN_ERROR, "project path expected (non-empty string)")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            raise RpcError(DOMAIN_ERROR, f"absolute path expected: {path!r}")
        if candidate.suffix != PROJECT_SUFFIX:
            candidate = candidate.with_name(candidate.name + PROJECT_SUFFIX)
        return str(candidate)

    def _exclusive(self) -> None:
        """One project in flight at a time: two writes would target the same file, and an
        open concurrent with a write would give a straddling snapshot."""
        if self._runner.has_active(SAVE_JOB) or self._runner.has_active(OPEN_JOB):
            raise RpcError(DOMAIN_ERROR, "A project operation is already in progress")

    # --- methods ---------------------------------------------------------------
    def save(self, path: str | None = None) -> dict:
        """Writes the session in the background and returns the job id."""
        target = self._resolve(path) if path else self._app.project_path
        if not target:
            raise RpcError(DOMAIN_ERROR, "No current project: supply a path.")
        self._exclusive()

        def work() -> dict:
            # The documents request happens here, in the job thread: waiting on the loop
            # would be precisely what prevents receiving the answer there.
            documents = self._service.request_documents()
            self._app.set_project_documents(documents)
            return self._app.save_project(target, documents=documents)

        return {"job": self._runner.submit_call(work, SAVE_JOB)}

    def open(self, path: str) -> dict:
        """Opens a project in the background and returns the job id."""
        target = self._resolve(path)
        self._exclusive()
        broadcast = self._service._broadcast

        def work() -> dict:
            report = self._app.open_project(target)
            if report.documents is not None:
                # After the work, hence after the `state.changed` that the end of the job
                # triggers: the per-step masks of the restored recipes designate views by
                # id, and the client must have seen them arrive.
                broadcast.notify("project.command",
                                 {"op": "restore_documents",
                                  "documents": report.documents})
            return report.to_dict()

        return {"job": self._runner.submit_call(work, OPEN_JOB)}

    def close(self) -> None:
        self._app.close_project()

    def store_documents(self, documents: Any = None, request: str | None = None) -> None:
        """Answer to ``request_documents``, or a spontaneous deposit from the client.

        The spontaneous deposit is not a detail: it is what keeps fresh the blob that the
        automatic end-of-session save will write, when no client is left to answer.
        """
        self._app.set_project_documents(documents)
        if request:
            self._service.deliver(request, documents)

    def recent(self) -> dict:
        return self._app.session.state()

    def set_reopen(self, enabled: bool) -> None:
        self._app.session.set_reopen(bool(enabled))

    def set_language(self, language: str | None = None) -> dict:
        """Sets the interface language (``None`` = follow the system).

        Returns the up-to-date session state: the client needs the **effective** language to
        decide whether it must reload, and would otherwise have learned it through one more
        round trip after the ``session.changed`` notification.
        """
        try:
            self._app.set_language(language)
        except ValueError as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from exc
        return self._app.session.state()
