"""Test JSON-RPC client.

Lives in its own module rather than in ``conftest.py``: pytest imports conftest files under
the name ``conftest``, so a test doing ``from tests.server.conftest import RpcFailure`` would
get a **second** class, and ``pytest.raises`` would never match.

A **background reader** drains the WebSocket continuously, like the real TypeScript client
does. The first version read on demand inside ``call()``, which made it impossible to send a
``console.interrupt`` while a ``console.execute`` was in flight — aiohttp refuses two
concurrent ``receive()`` calls. And that is exactly the scenario worth testing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from aiohttp import WSMsgType


class RpcFailure(AssertionError):
    """The server replied with a JSON-RPC error."""

    def __init__(self, error: dict) -> None:
        super().__init__(f"{error['code']}: {error['message']}")
        self.code = error["code"]
        self.error = error


class Session:
    """Numbered calls, with notifications collected in the background."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.notifications: list[dict] = []
        self._reader = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for message in self._ws:
                if message.type is not WSMsgType.TEXT:
                    continue
                payload = json.loads(message.data)
                if "method" in payload:
                    self.notifications.append(payload)
                    continue
                future = self._pending.pop(payload.get("id"), None)
                if future is not None and not future.done():
                    future.set_result(payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def call(self, method: str, **params: Any) -> Any:
        self._id += 1
        request_id = self._id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params:
            payload["params"] = params

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._ws.send_json(payload)
        response = await future

        if "error" in response:
            raise RpcFailure(response["error"])
        return response["result"]

    async def drain(self, timeout: float = 0.35) -> list[dict]:
        """Let the pending notifications land (snapshots, echo, viewport)."""
        await asyncio.sleep(timeout)
        return self.notifications

    def of(self, method: str) -> list[dict]:
        """Parameters of the notifications received for this method, in order."""
        return [n.get("params", {}) for n in self.notifications if n.get("method") == method]

    def text_of(self, method: str, field: str = "text") -> str:
        """Concatenate one field across the notifications — handy for standard output."""
        return "".join(str(params.get(field, "")) for params in self.of(method))

    def clear(self) -> None:
        self.notifications.clear()

    async def close(self) -> None:
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader
