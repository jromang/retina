"""Preferences seen from the network — console/GUI parity, in both directions.

What the contract requires: the panel and the console set the **same object**, a setting made
from one is announced to the other, and the client's form is built from the same `Parameter`
schema the processes use — so with no dedicated rendering code.
"""

from __future__ import annotations

import asyncio


async def _wait(session, event_: str, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if session.of(event_):
            return True
        await asyncio.sleep(0.02)
    return False


async def test_the_schema_arrives_grouped_and_translated(session):
    await session.call("hello")

    groups = await session.call("preferences.describe")

    assert [g["id"] for g in groups] == ["folders", "performance", "viewport", "session"]
    for group in groups:
        assert group["label"]
        for param in group["parameters"]:
            # The same projection as for a process: the client has no dedicated renderer.
            assert {"id", "type", "default", "label", "value"} <= set(param)


async def test_a_setting_made_over_the_network_reaches_the_domain(session, domain):
    await session.call("hello")

    stored = await session.call("preferences.set", key="performance.max_workers", value=7)

    assert stored == 7
    assert domain.preferences.get("performance.max_workers") == 7


async def test_an_out_of_range_value_is_clamped_and_returned(session):
    await session.call("hello")

    assert await session.call("preferences.set",
                              key="performance.max_workers", value=999) == 32


async def test_an_unknown_choice_becomes_a_clean_error(session):
    from rpcsession import RpcFailure

    await session.call("hello")

    try:
        await session.call("preferences.set", key="viewport.mask_display_mode", value="pink")
    except RpcFailure as failure:
        assert "outside the allowed values" in str(failure)
    else:
        raise AssertionError("an unknown choice must raise")


async def test_a_setting_is_announced_to_the_clients(session, domain):
    await session.call("hello")

    domain.preferences.set("viewport.readout_probe_size", 5)

    assert await _wait(session, "preferences.changed")


async def test_the_network_gesture_echoes_its_python(session):
    await session.call("hello")

    await session.call("preferences.set", key="performance.gpu_enabled", value=False)

    assert await _wait(session, "echo")
    codes = [e.get("code", "") for e in session.of("echo")]
    assert any("app.preferences.set('performance.gpu_enabled', False)" in c for c in codes)


async def test_reset_restores_the_default(session, domain):
    await session.call("hello")
    await session.call("preferences.set", key="performance.max_workers", value=9)

    await session.call("preferences.reset", key="performance.max_workers")

    assert domain.preferences.get("performance.max_workers") == 4


async def test_get_without_a_key_returns_everything(session):
    await session.call("hello")

    everything = await session.call("preferences.get")

    assert "performance.max_workers" in everything
    assert await session.call("preferences.get", key="performance.max_workers") == 4
