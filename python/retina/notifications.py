"""Notification center — console/GUI parity for durable events.

Pure domain (no shell import). The interface's toasts are only a *view* of this center: a
job error, a script's `app.notify(...)` — every event worth finding again after the fact
lives here, and the console reaches it just as the GUI does (``app.notifications``,
``app.notify``). The messages are raw content (often exception texts): they do not go
through gettext, the convention for internal errors.

Thread safety: ``add`` is called from the server's worker threads (end of a job) while the
loop reads ``all()`` for the snapshot — hence the lock. The ``on_changed`` hook is relayed
by the shell through ``Broadcaster.notify``/``mark_state_dirty``, both safe from any thread.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from .i18n import translate as _t

KINDS = ("info", "warning", "error")


@dataclass
class Notification:
    """A durable event, as the console and the GUI see it."""

    id: str
    kind: str
    message: str
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "message": self.message,
            "source": self.source,
            "timestamp": self.timestamp,
        }


class NotificationCenter:
    """Bounded queue of :class:`Notification`, most recent first.

    The bound is not a luxury: the whole center goes back out in every ``state.changed``
    snapshot, which must stay in the kilobyte range.
    """

    MAX = 50

    def __init__(self, echo: Callable[[str], None]) -> None:
        self._echo = echo
        self._items: list[Notification] = []
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        #: shell hook: ``(event, payload)`` with event ∈ ``added|dismissed|cleared``.
        self.on_changed: Callable[[str, dict], None] | None = None

    # --- reading ---------------------------------------------------------------
    def all(self) -> list[Notification]:
        with self._lock:
            return list(self._items)

    def __iter__(self) -> Iterator[Notification]:
        return iter(self.all())

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __repr__(self) -> str:
        return f"<NotificationCenter {len(self)} notification(s)>"

    # --- mutations ---------------------------------------------------------------
    def add(self, message: str, kind: str = "info", source: str = "") -> Notification:
        """Record an event. No echo: this is not a user gesture."""
        if kind not in KINDS:
            raise ValueError(_t("unknown kind: {kind!r} (expected: {expected})")
                             .format(kind=kind, expected=", ".join(KINDS)))
        with self._lock:
            note = Notification(id=f"n{next(self._counter)}", kind=kind,
                                message=str(message), source=source)
            self._items.insert(0, note)
            del self._items[self.MAX:]
        self._emit("added", note.to_dict())
        return note

    def dismiss(self, notification_id: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [n for n in self._items if n.id != notification_id]
            found = len(self._items) != before
        if found:
            self._emit("dismissed", {"id": notification_id})
        self._echo(f"app.notifications.dismiss({notification_id!r})")
        return found

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
        self._emit("cleared", {})
        self._echo("app.notifications.clear()")

    def _emit(self, event: str, payload: dict) -> None:
        if self.on_changed is not None:
            self.on_changed(event, payload)
