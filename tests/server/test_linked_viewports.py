"""Linked views — panning or zooming one window moves the others.

The basic comparison gesture: two layers of the same target side by side, explored together.
Two design points under test:

* the link lives **in the domain**, so it can be set from the console and is seen identically
  by two connected clients — it is not an interface state;
* it travels through the existing snapshot mechanism, without a dedicated event channel.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("astropy")

from retina.app import Application
from retina.model.image import Image


def _app(*sizes: tuple[int, int]) -> Application:
    app = Application()
    for rank, (width, height) in enumerate(sizes):
        app.new_window(Image(np.zeros((height, width, 1), np.float32)),
                       window_id=f"W{rank}")
    return app


# --- domain (console) ----------------------------------------------------------------

def test_linking_propagates_the_zoom_and_the_center(_=None):
    app = _app((100, 100), (100, 100))
    app.link_viewports()

    app.set_viewport((30, 40), zoom=2.0, window=app.windows[0])

    other = app.windows[1].viewport
    assert other.zoom == pytest.approx(2.0)
    assert other.center == pytest.approx((30, 40))


def test_linking_aligns_the_windows_right_away():
    """Without aligning up front, the first gesture would make the others jump for no reason."""
    app = _app((100, 100), (100, 100))
    app.set_viewport((10, 10), zoom=4.0, window=app.windows[0])
    app.set_active_window(app.windows[0])

    app.link_viewports()

    assert app.windows[1].viewport.zoom == pytest.approx(4.0)


def test_every_camera_gesture_propagates():
    """All six go through the same point — a future gesture cannot forget the link."""
    app = _app((100, 100), (100, 100))
    app.link_viewports()
    source, other = app.windows

    for gesture in (lambda: app.set_zoom(3.0, window=source),
                    lambda: app.zoom_in(window=source),
                    lambda: app.zoom_out(window=source),
                    lambda: app.zoom_1_1(window=source),
                    lambda: app.set_viewport((20, 20), zoom=2.0, window=source)):
        gesture()
        assert other.viewport.zoom == pytest.approx(source.viewport.zoom)
        assert other.viewport.center == pytest.approx(source.viewport.center)


def test_an_unlinked_window_does_not_move():
    app = _app((100, 100), (100, 100), (100, 100))
    app.link_viewports([app.windows[0], app.windows[1]])
    free = app.windows[2].viewport.zoom

    app.set_zoom(5.0, window=app.windows[0])

    assert app.windows[2].viewport.zoom == pytest.approx(free)


def test_a_gesture_on_an_unlinked_window_propagates_nothing():
    app = _app((100, 100), (100, 100), (100, 100))
    app.link_viewports([app.windows[0], app.windows[1]])
    before = app.windows[1].viewport.zoom

    app.set_zoom(7.0, window=app.windows[2])

    assert app.windows[1].viewport.zoom == pytest.approx(before)


def test_unlinking_stops_the_propagation():
    app = _app((100, 100), (100, 100))
    app.link_viewports()
    app.unlink_viewports()
    before = app.windows[1].viewport.zoom

    app.set_zoom(6.0, window=app.windows[0])

    assert app.linked_viewports() == []
    assert app.windows[1].viewport.zoom == pytest.approx(before)


def test_closing_a_window_unlinks_it():
    """A closed window can no longer be linked. Without that removal, ``linked_viewports()``
    would announce an id that designates nothing any more, and reopening an image bearing the
    same id would find it linked without anyone having asked for it."""
    app = _app((100, 100), (100, 100))
    app.link_viewports()
    assert app.linked_viewports() == ["W0", "W1"]

    app.close_window(app.windows[1])

    assert app.linked_viewports() == ["W0"]


def test_linked_windows_show_the_same_pixel():
    """Image coordinates, not a fraction of the frame: that is what we want in order to
    compare frames of a single target, which share their grid. A smaller image can therefore
    end up centered outside its field — the domain allows it, just as it allows panning past
    the edge."""
    app = _app((100, 100), (20, 20))
    app.link_viewports()

    app.set_viewport((90, 90), zoom=1.0, window=app.windows[0])

    small = app.windows[1].viewport
    assert small.zoom == pytest.approx(1.0)
    assert small.center == pytest.approx((90, 90))


def test_linking_an_unknown_window_raises():
    app = _app((100, 100))

    with pytest.raises(KeyError, match="Unknown window"):
        app.link_viewports(["Absent01"])


def test_the_link_echoes_in_python():
    app = _app((100, 100), (100, 100))
    echoes: list[str] = []
    app.on_echo = echoes.append

    app.link_viewports()
    app.unlink_viewports()

    assert "app.link_viewports()" in echoes
    assert "app.unlink_viewports()" in echoes


# --- over the network ----------------------------------------------------------------

async def test_the_link_shows_up_in_the_snapshot(session, client):
    client.retina.app.new_window(
        Image(np.zeros((16, 24, 3), np.float32)), window_id="Test02")

    linked = await session.call("app.link_viewports")

    assert set(linked) == {"Test01", "Test02"}
    snapshot = await session.call("state.snapshot")
    assert set(snapshot["linked_viewports"]) == {"Test01", "Test02"}


async def test_a_pan_carries_over_to_the_other_window(session, client):
    client.retina.app.new_window(
        Image(np.zeros((16, 24, 3), np.float32)), window_id="Test02")
    await session.call("app.link_viewports")

    await session.call("app.set_viewport", center=[8, 6], zoom=2.0, window="Test01")

    snapshot = await session.call("state.snapshot")
    other = next(w for w in snapshot["windows"] if w["id"] == "Test02")
    assert other["viewport"]["zoom"] == pytest.approx(2.0)
    assert other["viewport"]["center"] == pytest.approx([8, 6])


async def test_linking_an_unknown_window_returns_a_domain_error(session):
    from rpcsession import RpcFailure

    with pytest.raises(RpcFailure) as exc:
        await session.call("app.link_viewports", windows=["Absent01"])

    assert exc.value.code == -32000


async def test_without_a_link_the_snapshot_returns_an_empty_list(session):
    assert (await session.call("state.snapshot"))["linked_viewports"] == []
