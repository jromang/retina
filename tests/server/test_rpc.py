"""The RPC protocol: delegation to the domain, echo, snapshots, viewport notifications.

This file is the **console/GUI parity** test of the web shell: every RPC call must produce
exactly the Python echo that the same action typed in the console would have produced. If a
handler short-circuited ``app.*`` to "go faster", the echo would be missing and the test would
fall over.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from rpcsession import RpcFailure


async def test_an_rpc_call_delegates_to_the_domain_and_echoes(session, domain):
    """``app.set_zoom`` on the web side is ``app.set_zoom`` on the console side, echo included."""
    await session.call("hello")
    await session.call("app.set_zoom", zoom=4.0)

    assert domain.active_window.viewport.zoom == 4.0
    echoes = [p["code"] for p in (await session.drain()) and session.of("echo")]
    assert "app.set_zoom(4.0)" in echoes


async def test_a_mutation_triggers_a_snapshot(session, domain):
    await session.call("hello")
    await session.call("app.compute_auto_stf")
    await session.drain()

    snapshots = session.of("state.changed")
    assert snapshots, "no state.changed received after a mutation"
    view = snapshots[-1]["windows"][0]["views"][0]
    assert view["stf"]["channels"], "the computed STF must appear in the snapshot"


async def test_the_snapshot_coalesces_the_marks_of_a_single_burst(session, domain):
    """A call that dirties the state twice must produce only one snapshot.

    ``app.close_window`` marks the state a first time through ``on_windows_changed`` (the
    domain hook) and a second time because the method is declared mutating. Without
    coalescing, the client would receive two identical states — one of them already stale on
    arrival.

    Conversely, two *sequential* RPCs do produce two snapshots: the loop turns in between, and
    that is the intended behaviour.
    """
    domain.new_window(Image(np.zeros((4, 4, 1), dtype=np.float32)), window_id="Second")
    await session.call("hello")
    await session.drain()
    session.clear()

    await session.call("app.close_window", window="Second")
    await session.drain()

    assert len(session.of("state.changed")) == 1


async def test_a_pure_read_triggers_no_snapshot(session):
    await session.call("hello")
    await session.drain()
    session.notifications.clear()

    result = await session.call("app.readout", x=3.0, y=2.0)
    await session.drain()

    assert result is not None
    assert session.of("state.changed") == []


async def test_viewport_changed_carries_the_origin(session):
    """Whoever made the gesture must be able to ignore the echo of their own pan."""
    await session.call("hello")
    await session.call("app.set_viewport", center=[5.0, 5.0], zoom=2.0)
    await session.drain()

    events = session.of("viewport.changed")
    assert events, "no viewport.changed notification"
    assert events[-1]["origin"] is not None, "the origin identifies the calling connection"
    assert events[-1]["viewport"]["zoom"] == 2.0


async def test_a_mutation_outside_rpc_has_no_origin(session, domain):
    """An action coming from the console (not from an RPC) must be applied by every client."""
    await session.call("hello")
    await session.drain()
    session.notifications.clear()

    domain.set_zoom(8.0)  # exactly what `app.set_zoom(8)` typed in the console would do
    await session.drain()

    events = session.of("viewport.changed")
    assert events and events[-1]["origin"] is None


async def test_previews_in_the_snapshot(session, domain):
    await session.call("hello")
    preview_id = await session.call("app.new_preview", x0=2, y0=2, x1=10, y1=8)
    await session.drain()

    snapshot = session.of("state.changed")[-1]
    views = snapshot["windows"][0]["views"]
    preview = next(v for v in views if v["id"] == preview_id)
    assert preview["is_preview"] is True
    assert preview["rect"] == [2, 2, 10, 8]
    assert preview["volatile"] is True


async def test_history_serializes_labels_and_index(session, domain):
    from retina.processes.channels import Invert

    await session.call("hello")
    Invert().execute_on(domain.active_view)
    snapshot = await session.call("state.snapshot")

    history = snapshot["windows"][0]["views"][0]["history"]
    assert history["labels"] == ["initial", "Invert"]
    assert history["index"] == 1
    assert history["can_undo"] is True
    assert history["can_redo"] is False


async def test_undo_over_rpc(session, domain):
    from retina.processes.channels import Invert

    await session.call("hello")
    before = domain.active_view.image.data.copy()
    Invert().execute_on(domain.active_view)
    assert await session.call("app.undo") is True
    assert np.allclose(domain.active_view.image.data, before)


async def test_a_domain_error_comes_back_cleanly(session):
    """An unknown view is an application error, not a breakdown: code -32000, not -32603."""
    with pytest.raises(RpcFailure) as excinfo:
        await session.call("app.select_view", view="DoesNotExist")
    assert excinfo.value.code == -32000
    assert "KeyError" in str(excinfo.value)


async def test_invalid_parameters(session):
    with pytest.raises(RpcFailure) as excinfo:
        await session.call("app.set_zoom", factor=2.0)
    assert excinfo.value.code == -32602


async def test_an_invalid_enum_lists_the_accepted_values(session):
    with pytest.raises(RpcFailure) as excinfo:
        await session.call("app.set_interaction_mode", mode="teleportation")
    assert "'pan'" in str(excinfo.value)


async def test_a_valid_enum_is_converted(session, domain):
    from retina.model.viewport_state import InteractionMode

    await session.call("app.set_interaction_mode", mode="pan")
    assert domain.active_window.viewport.interaction_mode is InteractionMode.PAN


async def test_opening_a_window_notifies(session, domain):
    """``on_windows_changed`` is the only event the domain emits — it must be wired up."""
    await session.call("hello")
    await session.drain()
    session.notifications.clear()

    domain.new_window(Image(np.zeros((4, 4, 1), dtype=np.float32)), window_id="Added")
    await session.drain()

    snapshots = session.of("state.changed")
    assert snapshots
    assert "Added" in [w["id"] for w in snapshots[-1]["windows"]]


async def test_the_viewport_of_a_window_created_later_is_watched(session, domain):
    """``ViewportState.on_change`` has a single slot: new windows must be wired up too."""
    await session.call("hello")
    win = domain.new_window(Image(np.zeros((4, 4, 1), dtype=np.float32)), window_id="Late")
    await session.drain()
    session.notifications.clear()

    win.viewport.set_zoom(3.0)
    await session.drain()

    events = session.of("viewport.changed")
    assert [e["window"] for e in events] == ["Late"]


async def test_report_geometry_makes_zoom_to_fit_possible(session, domain):
    """Without geometry declared by the client, ``zoom_to_fit`` has no reference surface."""
    await session.call("viewport.report_geometry", window="Test01", vw=480.0, vh=320.0)
    await session.call("app.zoom_to_fit")

    vp = domain.active_window.viewport
    assert vp.zoom == pytest.approx(min(480.0 / 24, 320.0 / 16, 1.0))


async def test_rpc_methods_is_exposed(session):
    methods = await session.call("rpc.methods")
    assert methods["app.open"].startswith("Opens")
