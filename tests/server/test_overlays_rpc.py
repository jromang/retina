"""Overlays over the wire: five shapes, tags, and what the snapshot publishes.

These overlays are the only channel through which an interactive tool (DBE samples, PSF
ellipses, crop rectangle) draws on the image — and the same channel serves a script typed at
the console. So what is at stake here is parity: whatever the panel lays down, the console
must be able to lay down identically, and the snapshot must carry it through unchanged.
"""

from __future__ import annotations

import pytest
from rpcsession import RpcFailure


async def _overlays(session) -> list[dict]:
    snapshot = await session.call("state.snapshot")
    return snapshot["windows"][0]["viewport"]["overlays"]


async def test_the_five_shapes_cross_the_protocol(session):
    await session.call("hello")
    await session.call("app.add_overlay", kind="markers", points=[[1, 2], [3, 4]], size=9)
    await session.call("app.add_overlay", kind="lines", segments=[[[0, 0], [5, 5]]], width=2)
    await session.call("app.add_overlay", kind="text", items=[{"x": 1, "y": 2, "text": "NGC"}])
    await session.call(
        "app.add_overlay",
        kind="ellipses",
        items=[{"x": 10, "y": 12, "rx": 3, "ry": 2, "theta": 0.5}],
    )
    await session.call("app.add_overlay", kind="rects", rects=[[0, 0, 8, 6]], angle=15)

    overlays = await _overlays(session)
    assert [o["kind"] for o in overlays] == ["markers", "lines", "text", "ellipses", "rects"]
    # The data goes through **as is**: the server does not reinterpret it, it is the client
    # renderer that knows each shape's contract.
    assert overlays[0]["points"] == [[1, 2], [3, 4]]
    assert overlays[3]["items"][0]["theta"] == 0.5
    assert overlays[4]["angle"] == 15


async def test_clearing_by_tag(session):
    """Two tools open at the same time must not wipe each other out."""
    await session.call("hello")
    await session.call("app.add_overlay", kind="markers", tag="dbe", points=[[1, 1]])
    await session.call("app.add_overlay", kind="rects", tag="crop", rects=[[0, 0, 4, 4]])

    await session.call("app.clear_overlays", tag="dbe")
    remaining = await _overlays(session)
    assert [o["kind"] for o in remaining] == ["rects"]
    assert remaining[0]["tag"] == "crop"

    await session.call("app.clear_overlays")
    assert await _overlays(session) == []


async def test_set_overlays_replaces_a_tags_whole_set_in_one_gesture(session):
    """The primitive an interactive tool needs — and why it exists.

    A tool redraws its full set on every change. In two calls (clear, then add), the order of
    arrival is not guaranteed: two quick clicks used to leave the first one's markers on
    screen. Here, a single mutation.
    """
    await session.call("hello")
    await session.call("app.add_overlay", kind="rects", tag="crop", rects=[[0, 0, 4, 4]])
    await session.call(
        "app.set_overlays",
        tag="psf",
        overlays=[
            {"kind": "ellipses", "items": [{"x": 5, "y": 5, "rx": 2, "ry": 1, "theta": 0}]},
            {"kind": "text", "items": [{"x": 5, "y": 9, "text": "3.2 px"}]},
        ],
    )
    overlays = await _overlays(session)
    assert [o["kind"] for o in overlays] == ["rects", "ellipses", "text"]
    # The tag is applied by the domain: the caller need not repeat it on every overlay.
    assert all(o["tag"] == "psf" for o in overlays[1:])

    # A second set replaces the first without touching the other tags.
    await session.call(
        "app.set_overlays", tag="psf", overlays=[{"kind": "markers", "points": [[1, 1]]}]
    )
    overlays = await _overlays(session)
    assert [o["kind"] for o in overlays] == ["rects", "markers"]

    # An empty set clears the tag — that is how a tool withdraws.
    await session.call("app.set_overlays", tag="psf", overlays=[])
    assert [o["kind"] for o in await _overlays(session)] == ["rects"]


async def test_set_overlays_without_a_tag_is_refused(session):
    # Without a tag, the operation could not say *what* to replace: it would be a global
    # `clear_overlays` in disguise, carrying off the other tools' work.
    await session.call("hello")
    with pytest.raises(RpcFailure):
        await session.call("app.set_overlays", tag="", overlays=[])


async def test_an_unknown_shape_is_a_readable_domain_error(session):
    # Without an explicit conversion, the domain's ValueError would surface as an internal
    # error — the client would not know that it is *its own* parameter at fault.
    await session.call("hello")
    with pytest.raises(RpcFailure) as err:
        await session.call("app.add_overlay", kind="hologram", points=[[1, 1]])
    assert "hologram" in str(err.value)


async def test_an_overlay_triggers_a_snapshot(session):
    await session.call("hello")
    session.clear()
    await session.call("app.add_overlay", kind="markers", points=[[2, 2]])
    await session.drain()
    assert session.of("state.changed"), "an overlay that is laid down must reach the viewport"
    assert any("app.add_overlay('markers'" in p["code"] for p in session.of("echo"))
