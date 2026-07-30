"""Broadcasting notifications from the server to the clients.

Two responsibilities nothing else carries:

**Crossing the thread boundary.** Processes run in a pool; the domain calls ``on_echo`` and
``on_windows_changed`` there from a worker thread. Touching a WebSocket from there would be
the exact equivalent of touching the UI off the UI thread — the hard rule in
ARCHITECTURE.md. :meth:`Broadcaster.post` therefore republishes everything onto the asyncio
loop.

**Merging bursts.** A single user action often produces several mutations (``select_view``
then ``compute_auto_stf`` then ``set_zoom``). Emitting a full snapshot each time would send
three states, two of them stale. :meth:`mark_state_dirty` raises a flag; the snapshot is
built and sent only on the next loop turn, once.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from aiohttp import web

log = logging.getLogger("retina.server")


class Broadcaster:
    """Registry of connected clients + coalesced sending of notifications."""

    def __init__(self, snapshot_provider: Callable[[], dict]) -> None:
        self._snapshot_provider = snapshot_provider
        self._sockets: set[web.WebSocketResponse] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._state_dirty = False
        #: a send is already scheduled. A **boolean**, not the handle returned by
        #: ``call_soon_threadsafe``: the handle is known to the caller only *after* the call
        #: returns, yet the loop may have run the callback in the meantime. We would then
        #: overwrite the ``False`` set by ``_flush_state`` with an already-consumed handle —
        #: and no snapshot would ever go out again. The flag, in contrast, is raised *before*
        #: scheduling.
        self._flush_scheduled = False
        #: notifications emitted before any client was there (e.g. `app.layout.reset()` in a
        #: startup script) — replayed on the first `hello`.
        self._pending: list[dict] = []

    # --- life cycle -----------------------------------------------------------
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add(self, ws: web.WebSocketResponse) -> None:
        self._sockets.add(ws)

    def discard(self, ws: web.WebSocketResponse) -> None:
        self._sockets.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._sockets)

    # --- sending --------------------------------------------------------------
    async def send(self, payload: dict) -> None:
        """Send to every client. To be called from the loop."""
        dead: list[web.WebSocketResponse] = []
        for ws in list(self._sockets):
            if ws.closed:
                dead.append(ws)
                continue
            try:
                await ws.send_json(payload)
            except (ConnectionResetError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self._sockets.discard(ws)

    def notify(self, method: str, params: dict | None = None) -> None:
        """Publish a JSON-RPC notification from **any thread**."""
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.post(payload)

    def post(self, payload: dict) -> None:
        """Schedule a send on the loop, whatever the calling thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        if not self._sockets:
            # Nobody is listening yet: we keep a bounded trace for the first client.
            if len(self._pending) < 64:
                self._pending.append(payload)
            return
        loop.call_soon_threadsafe(self._spawn_send, payload)

    def _spawn_send(self, payload: dict) -> None:
        task = asyncio.ensure_future(self.send(payload))
        # without a reference, a task can be collected before it has run
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def flush_pending(self, ws: web.WebSocketResponse) -> None:
        """Replay to the new client what was emitted before it connected."""
        pending, self._pending = self._pending, []
        for payload in pending:
            await ws.send_json(payload)

    # --- coalesced snapshot ---------------------------------------------------
    def mark_state_dirty(self) -> None:
        """Signal that the state changed. The snapshot goes out on the next loop turn.

        Callable from any thread and as many times as one wants: several calls within the
        same burst produce a single send.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        self._state_dirty = True
        if not self._flush_scheduled:
            self._flush_scheduled = True
            loop.call_soon_threadsafe(self._flush_state)

    def _flush_state(self) -> None:
        # Lower the flag **before** reading ``_state_dirty``: a concurrent mutation that
        # still saw the flag raised would necessarily have already mutated the domain, so the
        # snapshot built below will contain it. The reverse order would lose that mutation.
        self._flush_scheduled = False
        if not self._state_dirty:
            return
        self._state_dirty = False
        try:
            snapshot = self._snapshot_provider()
        except Exception:
            log.exception("could not build the snapshot")
            return
        self.post({"jsonrpc": "2.0", "method": "state.changed", "params": snapshot})
