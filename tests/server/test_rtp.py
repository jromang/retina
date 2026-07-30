"""Real-time preview: decimation, generations, single owner.

The point to check is not that a preview gets computed — it is that a **stale** preview never
gets displayed. A slow computation started before a fast one would otherwise overwrite the
recent result, and the image would flicker back to a state the user has already left.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from retina.model.image import Image
from rpcsession import RpcFailure


async def _fetch(client, path: str):
    return await client.get(path, headers={"X-Retina-Token": client.retina.token})


async def _wait_ready(session, timeout: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        events = session.of("rtp.ready")
        if events:
            return events[-1]
        await asyncio.sleep(0.05)
    raise AssertionError(f"no rtp.ready within {timeout}s: {session.notifications}")


async def test_the_preview_is_decimated(client, session, domain):
    """A large image must produce a reduced preview — that is what makes it instantaneous."""
    domain.new_window(Image(np.zeros((2400, 3200, 3), dtype=np.float32)), window_id="Large")
    await session.call("hello")

    result = await session.call(
        "rtp.request", process_id="Invert", params={}, view="Large"
    )
    ready = await _wait_ready(session)

    assert ready["generation"] == result["generation"]
    # 3200 / ceil(3200/1024) = 3200/4 = 800
    assert max(ready["width"], ready["height"]) <= 1024
    assert ready["width"] < 3200


async def test_the_preview_does_not_touch_the_view(client, session, domain):
    """A preview applies nothing: no modified pixels, no history entry."""
    await session.call("hello")
    before = domain.active_view.image.data.copy()

    await session.call("rtp.request", process_id="Invert", params={}, view="Test01")
    await _wait_ready(session)

    assert np.allclose(domain.active_view.image.data, before)
    assert domain.active_view.history_labels() == ["initial"]


async def test_the_buffer_is_served_as_f16(client, session, domain):
    await session.call("hello")
    result = await session.call(
        "rtp.request", process_id="Invert", params={}, view="Test01"
    )
    ready = await _wait_ready(session)

    response = await _fetch(client, f"/api/rtp.f16?gen={result['generation']}")
    assert response.status == 200
    assert response.headers["X-Retina-Dtype"] == "float16"
    body = await response.read()
    assert len(body) == ready["width"] * ready["height"] * ready["channels"] * 2


async def test_a_stale_generation_is_refused(client, session, domain):
    """This is the central guarantee: we never serve an outdated preview."""
    await session.call("hello")
    first = await session.call("rtp.request", process_id="Invert", params={}, view="Test01")
    await _wait_ready(session)
    session.clear()

    second = await session.call(
        "rtp.request", process_id="GaussianConvolution", params={"sigma": 1.0}, view="Test01"
    )
    await _wait_ready(session)

    assert second["generation"] > first["generation"]
    stale = await _fetch(client, f"/api/rtp.f16?gen={first['generation']}")
    assert stale.status == 409
    fresh = await _fetch(client, f"/api/rtp.f16?gen={second['generation']}")
    assert fresh.status == 200


async def test_a_burst_publishes_only_the_last_one(client, session, domain):
    """Dragging a slider chains requests: only the last one must go through."""
    await session.call("hello")
    generations = []
    for sigma in (1.0, 2.0, 3.0, 4.0):
        result = await session.call(
            "rtp.request",
            process_id="GaussianConvolution",
            params={"sigma": sigma},
            view="Test01",
        )
        generations.append(result["generation"])
    await _wait_ready(session)

    last = generations[-1]
    assert (await _fetch(client, f"/api/rtp.f16?gen={last}")).status == 200
    for stale in generations[:-1]:
        assert (await _fetch(client, f"/api/rtp.f16?gen={stale}")).status == 409


async def test_release_frees_the_preview(client, session, domain):
    await session.call("hello")
    result = await session.call("rtp.request", process_id="Invert", params={}, view="Test01")
    await _wait_ready(session)

    await session.call("rtp.release")
    assert (await _fetch(client, f"/api/rtp.f16?gen={result['generation']}")).status == 409


async def test_a_release_from_another_owner_is_ignored(client, session, domain):
    """A form being closed must not cut off somebody else's preview."""
    await session.call("hello")
    result = await session.call(
        "rtp.request", process_id="Invert", params={}, view="Test01", owner="panel-A"
    )
    await _wait_ready(session)

    await session.call("rtp.release", owner="panel-B")
    assert (await _fetch(client, f"/api/rtp.f16?gen={result['generation']}")).status == 200

    await session.call("rtp.release", owner="panel-A")
    assert (await _fetch(client, f"/api/rtp.f16?gen={result['generation']}")).status == 409


async def test_a_global_process_is_refused(session):
    """A global process produces a window: there is nothing to preview."""
    with pytest.raises(RpcFailure) as excinfo:
        await session.call("rtp.request", process_id="Integration", params={}, view="Test01")
    assert "global" in str(excinfo.value)


async def test_an_invalid_parameter_is_refused(session):
    with pytest.raises(RpcFailure):
        await session.call(
            "rtp.request", process_id="Invert", params={"does_not_exist": 1}, view="Test01"
        )


async def test_an_unknown_view_is_refused(session):
    with pytest.raises(RpcFailure):
        await session.call("rtp.request", process_id="Invert", params={}, view="Ghost")


async def test_a_process_failure_is_reported(client, session, domain):
    await session.call("hello")
    await session.call(
        "rtp.request",
        process_id="PixelMath",
        params={"expression": "this_variable_does_not_exist"},
        view="Test01",
    )
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        if session.of("rtp.failed"):
            break
        await asyncio.sleep(0.05)
    assert session.of("rtp.failed"), "the failure should have been notified"


# --- the preview carries its view ---------------------------------------------------------
#
# The client panel renders the before/after curtain and the STF from the frame's view; without
# `view` in the notification it fell back on the *active* view — which may have changed during
# the computation, and the curtain then compared two different images without saying so.

async def test_the_preview_carries_its_view(session, domain):
    await session.call("hello")
    await session.call("rtp.request", process_id="Invert", params={}, view="Test01")
    ready = await _wait_ready(session)

    assert ready["view"] == "Test01"


async def test_a_failure_carries_its_view_too(session, domain):
    await session.call("hello")
    await session.call(
        "rtp.request",
        process_id="PixelMath",
        params={"expression": "this_variable_does_not_exist"},
        view="Test01",
    )
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        if session.of("rtp.failed"):
            break
        await asyncio.sleep(0.05)
    (failure,) = session.of("rtp.failed")
    assert failure["view"] == "Test01"


async def test_the_preview_on_a_preview(session, domain):
    """A preview IS a view: the real-time preview computes on its rectangle, not the window."""
    pv = domain.new_preview(4, 2, 20, 12, "zoom")  # the fixture image is 24×16
    await session.call("hello")

    await session.call("rtp.request", process_id="Invert", params={}, view=pv.id)
    ready = await _wait_ready(session)

    assert ready["view"] == pv.id
    assert (ready["width"], ready["height"]) == (16, 10)


async def test_changing_view_reuses_the_slot(session, client, domain):
    """Track View asks again on the new view: same owner, same slot."""
    pv = domain.new_preview(0, 0, 20, 20, "corner")
    await session.call("hello")

    first = await session.call(
        "rtp.request", process_id="Invert", params={}, view="Test01", owner="Invert"
    )
    await _wait_ready(session)
    session.clear()
    second = await session.call(
        "rtp.request", process_id="Invert", params={}, view=pv.id, owner="Invert"
    )
    ready = await _wait_ready(session)

    assert client.retina.rtp.owners() == ["Invert"]
    assert ready["view"] == pv.id
    assert (await _fetch(client, f"/api/rtp.f16?gen={first['generation']}")).status == 409
    assert (await _fetch(client, f"/api/rtp.f16?gen={second['generation']}")).status == 200


# --- several previews at once ------------------------------------------------------------
#
# [RETHOUGHT] A single form drove the preview, and ticking "Preview" on a second one evicted
# the first without saying so. Yet the question one asks in front of two settings is precisely
# "which of the two" — and a single preview cannot answer it.

async def test_two_forms_each_keep_their_preview(session):
    a = await session.call("rtp.request", process_id="Invert", view="Test01", owner="Invert")
    b = await session.call("rtp.request", process_id="Rescale", view="Test01", owner="Rescale")
    await session.drain(0.4)

    ready = {e["owner"]: e["generation"] for e in session.of("rtp.ready")}
    assert ready.get("Invert") == a["generation"]
    assert ready.get("Rescale") == b["generation"]


async def test_generations_stay_unique_across_owners(session):
    """It is the identifier /api/rtp.f16 carries: two previews cannot share it."""
    a = await session.call("rtp.request", process_id="Invert", view="Test01", owner="Invert")
    b = await session.call("rtp.request", process_id="Rescale", view="Test01", owner="Rescale")

    assert a["generation"] != b["generation"]


async def test_releasing_one_owner_leaves_the_other_intact(session, client):
    await session.call("rtp.request", process_id="Invert", view="Test01", owner="Invert")
    b = await session.call("rtp.request", process_id="Rescale", view="Test01", owner="Rescale")
    await session.drain(0.4)

    await session.call("rtp.release", owner="Invert")

    service = client.retina.rtp
    assert service.owners() == ["Rescale"]
    assert service.buffer_for(b["generation"]) is not None


async def test_past_the_limit_the_oldest_is_closed(session, client):
    from retina.server.rtp import MAX_PREVIEWS

    names = [f"P{i}" for i in range(MAX_PREVIEWS + 1)]
    for name in names:
        await session.call("rtp.request", process_id="Invert", view="Test01", owner=name)
    await session.drain(0.4)

    # A form left open and forgotten must not hold a decimated image forever; the client is
    # told, otherwise its panel would stay frozen on an image it will never receive again.
    assert client.retina.rtp.owners() == names[1:]
    assert [e["owner"] for e in session.of("rtp.released")] == [names[0]]
