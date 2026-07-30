"""Web server smoke test: authentication, asset serving, handshake.

Runs **without a browser** — the smoke test through a real browser is ``web/e2e/smoke.spec.ts``:
this one checks the frontend<->server<->domain wiring, not the rendering.
"""

from __future__ import annotations

import pytest
from retina.app import Application
from retina.server.core import PROTOCOL_VERSION, ServerApp
from retina.server.security import COOKIE_NAME, HEADER_NAME


async def test_ping_is_public(client):
    """The startup probe must not require the token: waiting for it is the whole point."""
    resp = await client.get("/api/ping")
    assert resp.status == 200
    assert (await resp.json())["protocol"] == PROTOCOL_VERSION


async def test_access_refused_without_a_token(client):
    resp = await client.get("/")
    assert resp.status == 401


async def test_token_by_header_then_cookie(client):
    """The header authenticates, and the response sets the cookie the assets will need."""
    token = client.retina.token
    resp = await client.get("/", headers={HEADER_NAME: token})
    # 200 if the frontend is built, 503 otherwise — either way, auth went through
    assert resp.status in (200, 503)
    assert resp.cookies[COOKIE_NAME].value == token


async def test_invalid_token_refused(client):
    resp = await client.get("/", headers={HEADER_NAME: "not-the-right-token"})
    assert resp.status == 401


async def test_the_websocket_refuses_a_foreign_origin(client):
    """WebSockets escape the same-origin policy: the Origin has to be checked here."""
    token = client.retina.token
    with pytest.raises(Exception):
        async with client.ws_connect(
            f"/ws?t={token}", headers={"Origin": "http://evil.example"}
        ):
            pass


async def test_hello_carries_the_protocol_and_the_snapshot(session):
    """The handshake gives the client everything it needs for its first render."""
    hello = await session.call("hello")
    assert hello["protocol"] == PROTOCOL_VERSION
    assert "app.open" in hello["methods"]
    snapshot = hello["snapshot"]
    assert snapshot["active_window"] == "Test01"
    assert [w["id"] for w in snapshot["windows"]] == ["Test01"]


async def test_unknown_method(session):
    from rpcsession import RpcFailure

    with pytest.raises(RpcFailure) as excinfo:
        await session.call("no.such.method")
    assert excinfo.value.code == -32601


async def test_invalid_json(client):
    token = client.retina.token
    async with client.ws_connect(f"/ws?t={token}") as ws:
        await ws.send_str("{this is not json")
        reply = await ws.receive_json()
    assert reply["error"]["code"] == -32700


def test_detach_leaves_the_domain_neutral(domain: Application):
    """Without this cleanup, two successive servers would leave dead hooks on ``app``."""
    server = ServerApp(domain, port=0)
    server.attach()
    assert domain.on_echo is not None
    assert domain.on_windows_changed is not None
    assert domain.windows[0].viewport.on_change is not None
    server.detach()
    assert domain.on_echo is None
    assert domain.on_windows_changed is None
    assert domain.windows[0].viewport.on_change is None
