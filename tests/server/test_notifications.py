"""Notifications: from a failing job to the bell, the full round trip.

The contract: a job error becomes a **durable** domain state (the notification centre),
broadcast by ``notification.added`` and carried by the snapshot — so it is still there after a
reconnection, where ``job.error`` alone evaporates along with the progress bar. And parity
cuts both ways: an ``app.notify`` typed at the console reaches the clients, and a dismiss over
RPC echoes its Python.
"""

from __future__ import annotations

import asyncio


async def _wait_notification(session, timeout: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        events = session.of("notification.added")
        if events:
            return events[-1]
        await asyncio.sleep(0.05)
    raise AssertionError(f"no notification within {timeout}s: {session.notifications}")


async def test_a_failing_job_feeds_the_centre(session, domain):
    await session.call("hello")
    await session.call(
        "process.run", process_id="PixelMath", params={"expression": "unknown_variable"}
    )
    note = await _wait_notification(session)
    assert note["kind"] == "error"
    assert note["source"] == "PixelMath"
    assert note["message"]
    # the domain carries it: that is what the snapshot will rebroadcast on reconnection
    assert any(n.id == note["id"] for n in domain.notifications)
    state = await session.call("hello")
    assert any(n["id"] == note["id"] for n in state["snapshot"]["notifications"])


async def test_dismiss_and_clear_over_rpc(session, domain):
    domain.notify("to be dismissed", source="test")
    note = await _wait_notification(session)

    assert await session.call("notifications.dismiss", id=note["id"]) is True
    await session.drain()
    assert session.of("notification.dismissed")[-1] == {"id": note["id"]}
    assert len(domain.notifications) == 0
    # the gesture echoes its Python, like every gesture in the interface
    codes = [e["code"] for e in session.of("echo")]
    assert f"app.notifications.dismiss({note['id']!r})" in codes

    domain.notify("one"), domain.notify("two")
    await session.call("notifications.clear")
    await session.drain()
    assert session.of("notification.cleared")
    assert len(domain.notifications) == 0


async def test_listing_and_hydration(session, domain):
    """A notification born before the connection is in the hello AND in list."""
    domain.notify("before connecting", kind="warning")
    state = await session.call("hello")
    assert state["snapshot"]["notifications"][0]["message"] == "before connecting"
    listed = await session.call("notifications.list")
    assert listed[0]["kind"] == "warning"


async def test_app_notify_from_the_console_pushes_to_the_clients(session, domain):
    """Parity: the script `app.notify(...)` is seen by the GUI with no GUI gesture."""
    await session.call("hello")
    domain.notify("Masters ready", source="recipe")
    note = await _wait_notification(session)
    assert note["message"] == "Masters ready"
    assert note["kind"] == "info"
    assert note["source"] == "recipe"
