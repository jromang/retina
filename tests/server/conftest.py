"""Shared fixtures for the web shell tests.

Every test gets a **fresh** :class:`~retina.app.Application`. Taking the singleton would let
the tests talk to each other through global state — and the hooks (``on_echo``,
``on_windows_changed``) would stay installed from one test to the next.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("aiohttp", reason="[web] extra missing")

from aiohttp.test_utils import TestClient, TestServer
from retina.app import Application
from retina.model.image import Image
from retina.server.core import ServerApp
from rpcsession import Session  # tests/server is on sys.path (no __init__.py)


def gradient(width: int = 24, height: int = 16, channels: int = 3) -> Image:
    """A deterministic, non-uniform image — a test run on zeros would see nothing."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    base = (x / max(width - 1, 1)) * 0.6 + (y / max(height - 1, 1)) * 0.3
    data = np.stack([base * (0.5 + 0.25 * c) for c in range(channels)], axis=-1)
    return Image(np.ascontiguousarray(data.astype(np.float32)))


@pytest.fixture
def domain() -> Application:
    app = Application()
    app.new_window(gradient(), window_id="Test01")
    return app


@pytest.fixture
def server(domain: Application) -> ServerApp:
    return ServerApp(domain, port=0)


@pytest.fixture
async def client(server: ServerApp):
    server.attach()
    async with TestClient(TestServer(server.aio)) as test_client:
        test_client.retina = server  # type: ignore[attr-defined]
        yield test_client
    server.detach()


@pytest.fixture
async def session(client):
    token = client.retina.token
    async with client.ws_connect(f"/ws?t={token}") as ws:
        rpc = Session(ws)
        try:
            yield rpc
        finally:
            await rpc.close()
