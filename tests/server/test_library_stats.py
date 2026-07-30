"""Instance library and histograms — the two supports of the drag-and-drop / STF milestone.

The library is the counterpart of the classic "process icons": a configured instance you set
aside, then drag onto a view. The histogram, for its part, feeds the STF handles — and must
come from the server, sole holder of the float32.
"""

from __future__ import annotations

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer
from retina.app import Application
from retina.model.image import Image
from retina.server.core import ServerApp
from rpcsession import RpcFailure, Session


@pytest.fixture
def isolated(tmp_path, monkeypatch) -> Application:
    """Isolated library: a test must never write into the real configuration."""
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path))
    app = Application()
    # ramp + noise: a histogram over zeros would say nothing
    ramp = np.linspace(0.0, 0.6, 32 * 24, dtype=np.float32).reshape(24, 32, 1)
    app.new_window(Image(np.repeat(ramp, 3, axis=2)), window_id="Test01")
    return app


@pytest.fixture
async def lib_session(isolated: Application):
    server = ServerApp(isolated, port=0)
    server.attach()
    async with (
        TestClient(TestServer(server.aio)) as client,
        client.ws_connect(f"/ws?t={server.token}") as ws,
    ):
        session = Session(ws)
        await session.call("hello")
        try:
            yield session, isolated
        finally:
            await session.close()
    server.detach()


# --- library -----------------------------------------------------------------
async def test_save_then_reread_an_instance(lib_session):
    session, _ = lib_session
    await session.call(
        "library.put",
        name="My deconvolution",
        processes=[{"process_id": "GaussianConvolution", "values": {"sigma": 4.5}}],
    )

    entries = await session.call("library.list")
    assert [e["name"] for e in entries] == ["My deconvolution"]
    assert entries[0]["kind"] == "instance"
    assert entries[0]["process_id"] == "GaussianConvolution"

    detail = await session.call("library.get", name="My deconvolution")
    assert detail["processes"][0]["values"]["sigma"] == 4.5


async def test_several_processes_form_a_recipe(lib_session):
    """A multi-process entry is a ProcessContainer — hence replayable as is."""
    session, _ = lib_session
    await session.call(
        "library.put",
        name="My pipeline",
        processes=[
            {"process_id": "GaussianConvolution", "values": {"sigma": 1.0}},
            {"process_id": "Invert", "values": {}},
        ],
    )
    entry = (await session.call("library.list"))[0]
    assert entry["kind"] == "container"
    assert entry["process_ids"] == ["GaussianConvolution", "Invert"]


async def test_the_desktop_position_is_persisted(lib_session):
    """Positions live in the entry itself, not in some interface setting."""
    session, _ = lib_session
    await session.call(
        "library.put", name="deconv",
        processes=[{"process_id": "Invert", "values": {}}],
    )
    assert (await session.call("library.list"))[0]["position"] is None

    await session.call("library.set_position", name="deconv", x=120.0, y=48.0)
    assert (await session.call("library.list"))[0]["position"] == [120.0, 48.0]


async def test_moving_an_icon_produces_the_echo(lib_session):
    session, _ = lib_session
    await session.call(
        "library.put", name="deconv",
        processes=[{"process_id": "Invert", "values": {}}],
    )
    session.clear()
    await session.call("library.set_position", name="deconv", x=10.0, y=20.0)
    await session.drain()
    assert "app.library.move('deconv', 10.0, 20.0)" in [p["code"] for p in session.of("echo")]


async def test_rename_and_delete(lib_session):
    session, _ = lib_session
    await session.call(
        "library.put", name="before", processes=[{"process_id": "Invert", "values": {}}]
    )
    await session.call("library.rename", old="before", new="after")
    assert [e["name"] for e in await session.call("library.list")] == ["after"]

    await session.call("library.delete", name="after")
    assert await session.call("library.list") == []


async def test_a_mutation_notifies_the_client(lib_session):
    """The library lives on disk, outside the snapshot: it has its own notification."""
    session, _ = lib_session
    session.clear()
    await session.call(
        "library.put", name="x", processes=[{"process_id": "Invert", "values": {}}]
    )
    await session.drain()
    assert session.of("library.changed")


async def test_an_unknown_entry_is_refused(lib_session):
    session, _ = lib_session
    with pytest.raises(RpcFailure):
        await session.call("library.get", name="never seen")
    with pytest.raises(RpcFailure):
        await session.call("library.delete", name="never seen")


async def test_an_unreadable_process_is_refused(lib_session):
    session, _ = lib_session
    with pytest.raises(RpcFailure) as excinfo:
        await session.call(
            "library.put", name="broken",
            processes=[{"process_id": "DoesNotExist", "values": {}}],
        )
    assert excinfo.value.code == -32000


# --- histogram ---------------------------------------------------------------
async def test_histogram_per_channel(lib_session):
    session, _ = lib_session
    result = await session.call("stats.histogram", view="Test01", bins=64)

    assert result["bins"] == 64
    assert len(result["channels"]) == 3
    counts = result["channels"][0]["counts"]
    assert len(counts) == 64
    assert sum(counts) == 32 * 24  # every pixel counted once


async def test_the_histogram_carries_the_robust_statistics(lib_session):
    """Median and MADN come from the domain's float32 — they are what drives the auto-STF."""
    session, domain = lib_session
    result = await session.call("stats.histogram", view="Test01")
    channel = result["channels"][0]
    assert channel["median"] == pytest.approx(domain.view("Test01").image.median(0), rel=1e-6)
    assert channel["madn"] > 0


async def test_the_cache_follows_the_pixel_generation(lib_session):
    """Changing the STF does not touch the pixels: the histogram must not be recomputed."""
    session, domain = lib_session
    first = await session.call("stats.histogram", view="Test01", bins=32)

    await session.call("app.compute_auto_stf")
    assert await session.call("stats.histogram", view="Test01", bins=32) == first

    from retina.processes.channels import Invert

    Invert().execute_on(domain.active_view)
    await session.call("state.snapshot")  # publishes the new generation
    after = await session.call("stats.histogram", view="Test01", bins=32)
    assert after != first, "the histogram should have changed after a process"


async def test_out_of_range_bins_are_refused(lib_session):
    session, _ = lib_session
    for bins in (1, 99999):
        with pytest.raises(RpcFailure):
            await session.call("stats.histogram", view="Test01", bins=bins)


async def test_an_unknown_view_is_refused(lib_session):
    session, _ = lib_session
    with pytest.raises(RpcFailure):
        await session.call("stats.histogram", view="Ghost")
