"""``app.layout`` driven from the console must genuinely move the frontend's panels.

This exercises the subtlest part of the protocol: the thirteen ``Protocol`` methods are
**synchronous** while the layout itself lives in the browser. The web backend therefore keeps
a local mirror (immediate reads) and pushes commands (writes). These tests check both
directions: the console drives the client, and the client reconciles the mirror.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer
from retina.app import Application
from retina.model.image import Image
from retina.server.core import ServerApp
from retina.server.layout_backend import (
    BUILTIN_PERSPECTIVES,
    PANELS,
    SIDEBAR_PANELS,
    ZONE_FALLBACK,
    ZONE_PANELS,
    ZONES,
    PerspectiveStore,
)
from rpcsession import RpcFailure, Session


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    """Isolates the perspectives: a test must write nothing into the real config."""
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def domain_isolated(config_dir) -> Application:
    app = Application()
    app.new_window(Image(np.zeros((8, 8, 1), dtype=np.float32)), window_id="Test01")
    return app


@pytest.fixture
async def layout_session(domain_isolated: Application):
    """Server + client, brought up once the config has been isolated."""
    server = ServerApp(domain_isolated, port=0)
    server.attach()
    async with (
        TestClient(TestServer(server.aio)) as test_client,
        test_client.ws_connect(f"/ws?t={server.token}") as ws,
    ):
        session = Session(ws)
        await session.call("hello")
        try:
            yield session, server, domain_isolated
        finally:
            await session.close()
    server.detach()


# --- panels -----------------------------------------------------------------
async def test_panel_ids_are_a_public_contract(layout_session):
    """Panel ids are public contract: a recipe names them literally.

    Changing them would silently break every recipe containing ``app.layout.show('console')``.
    """
    session, _, _ = layout_session
    panels = await session.call("layout.panels")
    assert set(panels) == set(PANELS)
    assert set(SIDEBAR_PANELS) <= set(panels)


async def test_the_file_explorer_is_a_sidebar_panel(layout_session):
    """It shares the sidebar's exclusivity: activating it collapses the others.

    Registering it in the center would make it a document, which an explorer is not — and
    ``web/tests/zones.test.ts`` checks the same thing from the other mirror.
    """
    _, _, domain = layout_session
    assert "files" in domain.layout.panels()
    domain.layout.activate("files")
    assert domain.layout.is_visible("files") is True
    assert domain.layout.is_visible("explorer") is False


async def test_reading_visibility_is_synchronous_on_the_domain_side(layout_session):
    """``app.layout.is_visible`` typed in the console must answer without a network trip."""
    _, _, domain = layout_session
    assert domain.layout.is_visible("console") is True
    assert domain.layout.is_visible("rtp") is False


async def test_show_from_the_console_pushes_a_command(layout_session):
    session, _, domain = layout_session
    domain.layout.show("rtp")  # exactly what the console would do
    await session.drain()

    commands = session.of("layout.command")
    assert {"op": "set_visible", "panel": "rtp", "visible": True} in commands
    assert domain.layout.is_visible("rtp") is True


async def test_toggle_flips_the_mirror(layout_session):
    _, _, domain = layout_session
    before = domain.layout.is_visible("console")
    domain.layout.toggle("console")
    assert domain.layout.is_visible("console") is not before


async def test_activate_applies_the_sidebar_exclusivity(layout_session):
    """VS Code rule: the sidebar shows only one view at a time."""
    session, _, domain = layout_session
    domain.layout.activate("history")
    await session.drain()

    assert domain.layout.is_visible("history") is True
    for other in SIDEBAR_PANELS:
        if other != "history":
            assert domain.layout.is_visible(other) is False
    # panels outside the group are left untouched
    assert domain.layout.is_visible("console") is True


async def test_activate_outside_the_sidebar_behaves_like_show(layout_session):
    _, _, domain = layout_session
    domain.layout.activate("explorer")
    domain.layout.activate("rtp")
    assert domain.layout.is_visible("rtp") is True
    assert domain.layout.is_visible("explorer") is True


async def test_an_unknown_panel_is_rejected(layout_session):
    session, _, _ = layout_session
    with pytest.raises(RpcFailure) as excinfo:
        await session.call("layout.show", panel="does_not_exist")
    assert "does_not_exist" in str(excinfo.value)


# --- action from the client → echo ------------------------------------------
async def test_a_client_click_produces_the_python_echo(layout_session):
    """Clicking an icon in the activity bar must write the equivalent Python line."""
    session, _, _ = layout_session
    await session.call("layout.activate", panel="library")
    await session.drain()

    echoes = [p["code"] for p in session.of("echo")]
    assert "app.layout.activate('library')" in echoes


async def test_lock_echoes_and_updates_the_mirror(layout_session):
    session, _, domain = layout_session
    await session.call("layout.lock", locked=True)
    await session.drain()

    assert domain.layout.locked is True
    assert "app.layout.lock(True)" in [p["code"] for p in session.of("echo")]


# --- reconciliation ---------------------------------------------------------
async def test_the_hello_carries_the_layout_to_adopt(domain_isolated: Application):
    """A script run BEFORE the interface opens must survive the connection.

    Regression: the first version had the client report its own defaults as soon as it
    connected, which silently overwrote the layout the script had set. The correct direction is
    the opposite — the server outlives connections, the client adopts.
    """
    server = ServerApp(domain_isolated, port=0)
    server.attach()
    try:
        domain_isolated.layout.activate("windows")  # as in a startup script
        domain_isolated.layout.show("rtp")

        async with (
            TestClient(TestServer(server.aio)) as test_client,
            test_client.ws_connect(f"/ws?t={server.token}") as ws,
        ):
            hello = await Session(ws).call("hello")

        layout = hello["layout"]
        assert layout["visible"]["windows"] is True
        assert layout["visible"]["explorer"] is False  # exclusivity applied
        assert layout["visible"]["rtp"] is True
        assert layout["locked"] is False
    finally:
        server.detach()


async def test_report_fixes_the_mirror(layout_session):
    """Closing a panel with the mouse must be reflected on the Python side.

    Without this, ``app.layout.is_visible('console')`` would lie to the console the moment the
    user touches the layout.
    """
    session, _, domain = layout_session
    assert domain.layout.is_visible("console") is True

    await session.call(
        "layout.report",
        visible={"console": False, "rtp": True},
        open_processes=["PixelMath"],
    )
    assert domain.layout.is_visible("console") is False
    assert domain.layout.is_visible("rtp") is True
    assert domain.layout.open_processes() == ["PixelMath"]


async def test_report_ignores_unknown_panels(layout_session):
    """A client from another version must not pollute the mirror."""
    session, server, _ = layout_session
    await session.call("layout.report", visible={"panel_from_the_future": True}, open_processes=[])
    assert "panel_from_the_future" not in server.layout._visible


async def test_report_does_not_emit_an_echo(layout_session):
    """The report is not a user action: echoing it would pollute the console."""
    session, _, _ = layout_session
    session.clear()
    await session.call("layout.report", visible={"console": False}, open_processes=[])
    await session.drain()
    assert session.of("echo") == []


# --- collapsible zones ------------------------------------------------------
async def test_the_zones_are_announced(layout_session):
    session, _, _ = layout_session
    assert await session.call("layout.zones") == list(ZONES)


async def test_a_zone_is_derived_from_its_panels(layout_session):
    """No second mirror: a zone is visible iff one of its panels is."""
    _, _, domain = layout_session
    for panel in ZONE_PANELS["bottom"]:
        domain.layout.hide(panel)
    assert domain.layout.is_zone_visible("bottom") is False

    domain.layout.show("rtp")
    assert domain.layout.is_zone_visible("bottom") is True


async def test_hide_zone_closes_all_its_panels(layout_session):
    session, _, domain = layout_session
    domain.layout.hide_zone("bottom")
    await session.drain()

    assert domain.layout.is_zone_visible("bottom") is False
    assert all(not domain.layout.is_visible(p) for p in ZONE_PANELS["bottom"])
    assert {
        "op": "set_zone_visible",
        "zone": "bottom",
        "visible": False,
        "panels": [],
    } in session.of("layout.command")


async def test_show_zone_reopens_the_last_active_panel(layout_session):
    """The hard part: collapsing then expanding must give back History, not the Explorer."""
    _, _, domain = layout_session
    domain.layout.activate("history")
    domain.layout.hide_zone("sidebar")
    domain.layout.show_zone("sidebar")

    assert domain.layout.is_visible("history") is True
    assert domain.layout.is_visible("explorer") is False


async def test_the_zone_memory_follows_mouse_gestures(layout_session):
    """Closing a panel with the mouse goes through ``report`` — the memory must learn it.

    Otherwise collapse/expand would reopen the panel Python *believed* was open, not the one the
    user was actually looking at.
    """
    session, _, domain = layout_session
    visible = dict.fromkeys(PANELS, False)
    visible["library"] = True
    await session.call("layout.report", visible=visible, open_processes=[])

    domain.layout.hide_zone("sidebar")
    domain.layout.show_zone("sidebar")
    assert domain.layout.is_visible("library") is True
    assert domain.layout.is_visible("explorer") is False


async def test_show_zone_without_memory_falls_back_to_the_default(layout_session):
    """A zone never opened has nothing to reopen: we take the default panel."""
    _, _, domain = layout_session
    for panel in ZONE_PANELS["bottom"]:
        domain.layout.hide(panel)
    # we erase the memory too, to simulate a zone that was never expanded
    domain.layout._backend._zone_memory.pop("bottom", None)  # type: ignore[attr-defined]

    domain.layout.show_zone("bottom")
    assert domain.layout.is_visible(ZONE_FALLBACK["bottom"]) is True


async def test_toggle_zone_echoes_the_python(layout_session):
    session, _, _ = layout_session
    await session.call("layout.toggle_zone", zone="bottom")
    await session.drain()

    assert "app.layout.toggle_zone('bottom')" in [p["code"] for p in session.of("echo")]


async def test_an_unknown_zone_is_rejected(layout_session):
    session, _, _ = layout_session
    with pytest.raises(RpcFailure) as excinfo:
        await session.call("layout.show_zone", zone="middle")
    assert "middle" in str(excinfo.value)


async def test_zones_are_noops_in_headless():
    """With no backend, a recipe that collapses a zone must not blow up — but must echo."""
    app = Application()
    echoes: list[str] = []
    app.on_echo = echoes.append

    assert app.layout.zones() == []
    assert app.layout.is_zone_visible("sidebar") is False
    app.layout.toggle_zone("sidebar")
    assert "app.layout.toggle_zone('sidebar')" in echoes


# --- process windows --------------------------------------------------------
async def test_open_process_expands_the_right_zone(layout_session):
    """Opening a form inside a collapsed zone would show nothing."""
    _, _, domain = layout_session
    domain.layout.hide_zone("right")
    assert domain.layout.is_zone_visible("right") is False

    domain.layout.open_process("Invert")
    assert domain.layout.is_zone_visible("right") is True


async def test_open_and_close_process_are_tracked_in_the_snapshot(layout_session):
    session, _, domain = layout_session
    await session.call("layout.open_process", process_id="GaussianConvolution")
    await session.drain()

    assert domain.layout.open_processes() == ["GaussianConvolution"]
    snapshot = session.of("state.changed")[-1]
    assert snapshot["layout"]["open_processes"] == ["GaussianConvolution"]

    await session.call("layout.close_process", process_id="GaussianConvolution")
    assert domain.layout.open_processes() == []


async def test_open_process_is_idempotent(layout_session):
    _, _, domain = layout_session
    domain.layout.open_process("Invert")
    domain.layout.open_process("Invert")
    assert domain.layout.open_processes() == ["Invert"]


async def test_open_process_carries_the_starting_values(layout_session):
    """Double-click on a recipe step: the form opens already filled with its values.

    The gesture comes from the recipe editor, but the capability belongs to the domain — hence
    the same line in the console: ``app.layout.open_process('GaussianConvolution',
    {'sigma': 3.5})``.
    """
    session, _, domain = layout_session
    await session.call(
        "layout.open_process", process_id="GaussianConvolution", values={"sigma": 3.5}
    )
    await session.drain()

    command = [c for c in session.of("layout.command") if c.get("op") == "open_process"][-1]
    assert command["values"] == {"sigma": 3.5}
    assert domain.layout.open_processes() == ["GaussianConvolution"]


async def test_the_starting_values_are_not_remembered(layout_session):
    """These are *starting* values, which the user then edits.

    Keeping them in the layout state would replay them at every reconnection, wiping out the
    settings made since.
    """
    session, _, domain = layout_session
    domain.layout.open_process("GaussianConvolution", {"sigma": 3.5})
    await session.drain()
    assert "values" not in str(domain.layout.open_processes())

    session.clear()
    hello = await session.call("hello")
    assert hello["layout"]["open_processes"] == ["GaussianConvolution"]


async def test_open_process_with_values_echoes_the_complete_line(layout_session):
    session, _, domain = layout_session
    domain.layout.open_process("GaussianConvolution", {"sigma": 3.5})
    await session.drain()
    echoes = [p["code"] for p in session.of("echo")]
    assert "app.layout.open_process('GaussianConvolution', {'sigma': 3.5})" in echoes


# --- perspectives -----------------------------------------------------------
async def test_the_built_in_presets_are_announced(layout_session):
    session, _, _ = layout_session
    assert set(BUILTIN_PERSPECTIVES) <= set(await session.call("layout.perspectives"))


async def test_loading_a_preset_pushes_the_command(layout_session):
    session, _, _ = layout_session
    assert await session.call("layout.load", name="Inspection") is True
    await session.drain()
    assert {"op": "load_builtin", "name": "Inspection"} in session.of("layout.command")


async def test_loading_an_unknown_perspective_returns_false(layout_session):
    session, _, _ = layout_session
    assert await session.call("layout.load", name="Never seen") is False


async def test_perspective_save_round_trip(layout_session, config_dir):
    """save → the client serializes → store_perspective → the file exists and reloads."""
    session, _, _ = layout_session

    await session.call("layout.save", name="My wide screen")
    await session.drain()
    assert {"op": "request_save", "name": "My wide screen"} in session.of("layout.command")

    blob = {"grid": {"root": "fake-dockview-state"}, "sidebar": "explorer"}
    await session.call("layout.store_perspective", name="My wide screen", layout=blob)

    files = list((config_dir / "perspectives").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["layout"] == blob

    assert "My wide screen" in await session.call("layout.perspectives")
    assert await session.call("layout.load", name="My wide screen") is True
    await session.drain()
    loaded = [c for c in session.of("layout.command") if c["op"] == "load_perspective"]
    assert loaded[-1]["layout"] == blob


async def test_deleting_a_perspective(layout_session):
    session, _, _ = layout_session
    await session.call("layout.store_perspective", name="Temporary", layout={"a": 1})
    assert "Temporary" in await session.call("layout.perspectives")
    await session.call("layout.delete", name="Temporary")
    assert "Temporary" not in await session.call("layout.perspectives")


async def test_reset_restores_the_default_visibility(layout_session):
    session, _, domain = layout_session
    domain.layout.hide("console")
    domain.layout.show("rtp")
    domain.layout.reset()
    await session.drain()

    assert domain.layout.is_visible("console") is True
    assert domain.layout.is_visible("rtp") is False
    assert {"op": "reset"} in session.of("layout.command")


def test_the_store_ignores_a_corrupted_file(tmp_path):
    """A damaged JSON must not make the whole list of perspectives disappear."""
    store = PerspectiveStore(tmp_path)
    store.save("Good", {"ok": True})
    (tmp_path / "broken.json").write_text("{ not json at all", encoding="utf-8")
    assert store.names() == ["Good"]


def test_the_backend_without_a_client_does_not_lose_commands(domain_isolated):
    """A script launched before the window opens must still be applied."""
    server = ServerApp(domain_isolated, port=0)
    server.attach()
    try:
        domain_isolated.layout.activate("history")
        # No asyncio loop and no client: the command is set aside, and the local mirror stays
        # correct — it is the one that answers the console.
        assert domain_isolated.layout.is_visible("history") is True
    finally:
        server.detach()
