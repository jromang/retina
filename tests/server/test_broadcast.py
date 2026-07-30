"""Snapshot coalescing — and the race that had broken it.

``mark_state_dirty`` is called from worker threads (job completion, ``on_windows_changed``)
while the flush runs on the asyncio loop. The two tests below bracket the contract: one
snapshot per burst, but **never zero**.
"""

from __future__ import annotations

import asyncio
import threading

from retina.server.broadcast import Broadcaster


class _ImmediateLoop:
    """A fake loop that runs the callback *during* ``call_soon_threadsafe``.

    This is a real loop's worst-case interleaving: the worker thread schedules the flush, the
    loop consumes it, and the worker thread still has not finished its own statement. An
    implementation that remembers the handle *returned* by the call then overwrites the state
    the flush had reset — and no snapshot ever goes out again. This class makes that bug
    deterministic.
    """

    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, callback, *args):  # type: ignore[no-untyped-def]
        callback(*args)
        return object()  # a dummy handle, as asyncio would return


def test_a_snapshot_goes_out_again_after_every_burst() -> None:
    sent: list[dict] = []
    bus = Broadcaster(lambda: {"rev": len(sent)})
    bus._loop = _ImmediateLoop()  # type: ignore[assignment]
    bus.post = sent.append  # type: ignore[method-assign]

    bus.mark_state_dirty()
    assert len(sent) == 1, "first snapshot"

    # The case that used to regress: the second mutation must not be swallowed by the flag.
    bus.mark_state_dirty()
    assert len(sent) == 2, "a consumed flush must allow a following one"


def test_a_burst_produces_only_one_snapshot() -> None:
    """The counterpart: the coalescing must hold when the loop really is deferred."""
    sent: list[dict] = []

    async def scenario() -> None:
        bus = Broadcaster(lambda: {"rev": 1})
        bus.bind_loop(asyncio.get_running_loop())
        bus.post = sent.append  # type: ignore[method-assign]

        done = threading.Event()

        def worker() -> None:
            for _ in range(20):
                bus.mark_state_dirty()
            done.set()

        threading.Thread(target=worker).start()
        await asyncio.to_thread(done.wait)
        await asyncio.sleep(0)  # let the scheduled flush(es) run
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert sent, "the burst must produce at least one snapshot"
    assert len(sent) <= 2, f"20 marks must not produce 20 snapshots (got {len(sent)})"
