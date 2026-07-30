"""Blink — the sequence inspector, from the domain up to the network.

Two guarantees carry this file:

1. **Nothing is read before it is looked at.** An earlier version loaded the whole sequence
   into memory on opening; on fifteen frames of 26 Mpx that is already 4.7 GB. The test
   counts the actual reads rather than trusting a reading of the code.
2. **Stepping creates no new channel.** Replacing the window's pixels is enough: the
   generation advances, the snapshot goes out again, the viewport reloads.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("astropy")

from retina.app import Application
from retina.io.fits import save_fits
from retina.model.image import Image


@pytest.fixture
def sequence(tmp_path) -> list[str]:
    """Five frames of increasing levels — the ground truth of stepping."""
    paths = []
    for i in range(5):
        path = str(tmp_path / f"light_{i:03d}.fits")
        save_fits(path, Image(np.full((8, 8, 1), 0.1 * (i + 1), np.float32)),
                  {"EXPTIME": 60.0, "FILTER": "L"})
        paths.append(path)
    return paths


# --- domain (console) ----------------------------------------------------------------

def test_opening_reads_no_pixel(sequence, monkeypatch):
    """The hard point: `load` must touch nothing but the headers."""
    from retina.processes import inspection

    reads: list[str] = []
    real = inspection.Blink.array_at

    def count(self, index):
        reads.append(self.frames[index % len(self.frames)])
        return real(self, index)

    monkeypatch.setattr(inspection.Blink, "array_at", count)
    blink = inspection.Blink(frames=sequence)

    described = blink.load()

    assert reads == []
    assert [d["name"] for d in described] == [f"light_{i:03d}.fits" for i in range(5)]
    assert described[0]["exposure"] == 60.0  # read from the header, not from the pixels


def test_visiting_a_frame_reads_only_that_one(sequence, monkeypatch):
    from retina.processes import inspection

    reads: list[str] = []
    real = inspection.Blink.array_at

    def count(self, index):
        reads.append(self.frames[index % len(self.frames)])
        return real(self, index)

    monkeypatch.setattr(inspection.Blink, "array_at", count)
    blink = inspection.Blink(frames=sequence)
    blink.load()

    blink.stats_at(2)

    assert reads == [sequence[2]]


def test_the_cache_avoids_rereading_a_round_trip(sequence):
    """Going and coming back is the blink gesture itself: it must cost nothing."""
    from retina.processes.inspection import CACHE_SIZE, Blink

    blink = Blink(frames=sequence)
    blink.load()
    first = blink.array_at(0)

    blink.array_at(1)

    assert blink.array_at(0) is first
    assert len(blink._cache) <= CACHE_SIZE


def test_the_cache_stays_bounded_on_a_long_sequence(sequence):
    """This is what makes a hundred-frame sequence openable."""
    from retina.processes.inspection import CACHE_SIZE, Blink

    blink = Blink(frames=sequence)
    blink.load()
    for i in range(len(sequence)):
        blink.array_at(i)

    assert len(blink._cache) == CACHE_SIZE


def test_stepping_wraps_around_in_both_directions(sequence):
    from retina.processes.inspection import Blink

    blink = Blink(frames=sequence)
    blink.load()

    assert blink.step(-1) == 4
    assert blink.step(1) == 0
    assert blink.go_to(12) == 2


def test_the_statistics_are_computed_only_once(sequence):
    from retina.processes.inspection import Blink

    blink = Blink(frames=sequence)
    blink.load()

    first = blink.stats_at(3)

    assert blink.stats_at(3) is first
    assert first["median"] == pytest.approx(0.4)


def test_stepping_reuses_the_same_window(sequence):
    """One window per frame would leave a hundred of them behind."""
    app = Application()
    app.blink(sequence)
    windows = len(app.windows)

    app.blink_step(1)
    app.blink_step(1)

    assert len(app.windows) == windows
    assert np.median(app.windows[-1].main_view.image.data) == pytest.approx(0.3)


def test_stepping_without_an_open_sequence_raises(sequence):
    app = Application()

    with pytest.raises(RuntimeError, match="No open sequence"):
        app.blink_step(1)


def test_a_closed_window_is_reopened_rather_than_raising(sequence):
    """Closing the tab then clicking "next" is a harmless gesture, not an error."""
    app = Application()
    app.blink(sequence)
    app.close_window(app.windows[-1])

    index = app.blink_step(1)

    assert index == 1
    assert len(app.windows) == 1


def test_opening_echoes_in_python(sequence):
    app = Application()
    echoes: list[str] = []
    app.on_echo = echoes.append

    app.blink(sequence)
    app.blink_step(1)

    assert any(code.startswith("app.blink([") for code in echoes)
    assert "app.blink_step(1)" in echoes


# --- over the network ----------------------------------------------------------------

async def test_the_handler_opens_and_returns_the_state(session, sequence):
    state = await session.call("app.blink", frames=sequence)

    assert state["count"] == 5
    assert state["index"] == 0
    assert state["stats"]["median"] == pytest.approx(0.1)


async def test_the_step_returns_the_complete_state(session, sequence):
    """One more round trip just for the statistics would show up on fast stepping."""
    await session.call("app.blink", frames=sequence)

    state = await session.call("app.blink_step", delta=2)

    assert state["index"] == 2
    assert state["stats"]["median"] == pytest.approx(0.3)


async def test_stepping_advances_the_pixel_generation(session, sequence):
    """No new channel: the viewport refreshes through the snapshot mechanism."""
    state = await session.call("app.blink", frames=sequence)
    window = state["window"]

    def gen(snapshot):
        win = next(w for w in snapshot["windows"] if w["id"] == window)
        return win["views"][0]["pixel_gen"]

    before = gen(await session.call("state.snapshot"))
    await session.call("app.blink_step", delta=1)
    after = gen(await session.call("state.snapshot"))

    assert after != before


async def test_stepping_without_a_sequence_returns_a_domain_error(session):
    from rpcsession import RpcFailure

    with pytest.raises(RpcFailure) as exc:
        await session.call("app.blink_step", delta=1)

    assert exc.value.code == -32000


async def test_the_state_is_null_as_long_as_no_sequence_is_open(session):
    assert await session.call("app.blink_state") is None
