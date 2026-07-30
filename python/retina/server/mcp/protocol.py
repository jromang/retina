"""The MCP protocol, and its "streamable HTTP" transport mounted in aiohttp.

# Why not take the official SDK

The ``mcp`` SDK is built on ASGI (Starlette/anyio); grafting it into our aiohttp server would
require an ASGI bridge, and running it alongside would open a second port with its own
authentication — whereas the project's whole security model rests on "one port, one token,
loopback" (``server/security.py``). Yet the server side of the protocol is JSON-RPC 2.0 with
a dozen methods: exactly what ``server/rpc.py`` already does for the web shell. So we write
it, and the repository keeps a single way of routing a call.

# What "streamable HTTP" requires

A single endpoint that accepts ``POST`` (a JSON-RPC request, answered in JSON or SSE),
``GET`` (an SSE stream opened by the client to receive unsolicited messages) and ``DELETE``
(end of session). The server assigns an ``Mcp-Session-Id`` on ``initialize`` and the client
sends it back afterwards.

We answer POSTs in **JSON** rather than SSE: our responses are complete and immediate, and
nothing precedes them that would need streaming. The GET is accepted and held open with
heartbeat comments — we do not yet emit any server→client notification (job progress will
come through it the day we need it), but a client that opens it must not receive a 405:
several treat that as a fatal error.

# Protocol error vs tool error

A tool that fails is **not** a JSON-RPC error: it returns a result with ``isError: true``.
The distinction matters — a protocol error reaches the client as a transport fault, which the
model does not see, whereas the failed result reaches it and lets it correct its call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any

from aiohttp import web

from . import PROTOCOL_VERSION, SERVER_INFO
from .tools import ToolRegistry

if TYPE_CHECKING:
    from ..core import ServerApp

log = logging.getLogger("retina.server.mcp")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

SESSION_HEADER = "Mcp-Session-Id"
#: Interval of the SSE comments that keep the GET stream open across proxies.
HEARTBEAT_SECONDS = 25.0


class McpServer:
    """The protocol, independently of the transport (HTTP or stdio).

    One instance per Retina server: the MCP session has no state of its own beyond the
    registry, which is the application's.
    """

    def __init__(self, server: ServerApp) -> None:
        self.registry = ToolRegistry(server)
        self._server = server
        self._sessions: set[str] = set()

    # --- sessions -------------------------------------------------------------
    def new_session(self) -> str:
        session = secrets.token_hex(16)
        self._sessions.add(session)
        return session

    def end_session(self, session: str | None) -> bool:
        if session is None:
            return False
        known = session in self._sessions
        self._sessions.discard(session)
        return known

    # --- dispatch -------------------------------------------------------------
    async def handle(self, message: dict) -> dict | None:
        """Handles a JSON-RPC request. Returns ``None`` for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(message.get("id") if isinstance(message, dict) else None,
                          INVALID_REQUEST, "expected a JSON-RPC 2.0 message")

        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if not isinstance(method, str):
            return _error(request_id, INVALID_REQUEST, "missing method")

        # Notifications (no `id`) never receive an answer — including
        # `notifications/initialized`, which the client sends after the handshake.
        if request_id is None:
            return None

        try:
            result = await self._call(method, params)
        except _McpError as exc:
            return _error(request_id, exc.code, exc.message)
        except Exception as exc:  # pragma: no cover — safety net, never expected
            log.exception("MCP: %s failed", method)
            return _error(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    async def _call(self, method: str, params: dict) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.registry.definitions()}
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str):
                raise _McpError(INVALID_PARAMS, "tools/call requires a tool name")
            result = await self.registry.call(name, params.get("arguments") or {})
            return result.to_dict()
        if method == "resources/list":
            from .resources import list_resources

            return {"resources": list_resources()}
        if method == "resources/templates/list":
            from .resources import list_templates

            return {"resourceTemplates": list_templates()}
        if method == "resources/read":
            from .resources import read_resource

            uri = params.get("uri")
            if not isinstance(uri, str):
                raise _McpError(INVALID_PARAMS, "resources/read requires a uri")
            contents = read_resource(uri)
            if contents is None:
                raise _McpError(INVALID_PARAMS, f"unknown resource: {uri}")
            return {"contents": [contents]}
        if method == "prompts/list":
            from .prompts import list_prompts

            return {"prompts": list_prompts()}
        if method == "prompts/get":
            from .prompts import get_prompt

            name = params.get("name")
            if not isinstance(name, str):
                raise _McpError(INVALID_PARAMS, "prompts/get requires a name")
            prompt = get_prompt(name, params.get("arguments") or {})
            if prompt is None:
                raise _McpError(INVALID_PARAMS, f"unknown prompt: {name}")
            return prompt
        raise _McpError(METHOD_NOT_FOUND, f"unknown method: {method}")

    def _initialize(self, params: dict) -> dict:
        # We return *our* version. A more recent client knows how to fall back; an older one
        # receives a version it does not know and cuts short — which is better than a
        # dialogue of the deaf over semantics that have changed.
        requested = params.get("protocolVersion")
        if requested and requested != PROTOCOL_VERSION:
            log.info("MCP: client at %s, server at %s", requested, PROTOCOL_VERSION)
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
            "instructions": INSTRUCTIONS,
        }


INSTRUCTIONS = (
    "Retina is an astronomical image processing application. This server exposes the live "
    "session the user is looking at: opening files, applying processes, inspecting "
    "statistics, and running the automated pre-processing pipeline.\n"
    "Start with get_state to see what is open. Astronomical images are linear and look "
    "black until stretched — use set_stf(mode='auto') and render_view to actually see one. "
    "Every process you apply goes onto the view's history and can be undone, so you can "
    "work without asking permission for each step. Prefer the typed tools; execute_python "
    "runs in the user's own IPython console when nothing else fits."
)


class _McpError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


# --------------------------------------------------------------------------- #
# HTTP transport                                                               #
# --------------------------------------------------------------------------- #
class McpEndpoint:
    """The ``/mcp`` routes: POST (calls), GET (SSE stream), DELETE (end of session)."""

    def __init__(self, server: ServerApp) -> None:
        self.mcp = McpServer(server)

    def add_routes(self, router: web.UrlDispatcher, path: str = "/mcp") -> None:
        router.add_post(path, self.post)
        router.add_get(path, self.get)
        router.add_delete(path, self.delete)

    async def post(self, request: web.Request) -> web.StreamResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response(_error(None, PARSE_ERROR, "invalid JSON"), status=400)

        headers: dict[str, str] = {}
        # An `initialize` request opens a session; the next ones carry its id.
        if isinstance(payload, dict) and payload.get("method") == "initialize":
            headers[SESSION_HEADER] = self.mcp.new_session()

        if isinstance(payload, list):  # JSON-RPC batch
            replies = [r for r in [await self.mcp.handle(m) for m in payload] if r is not None]
            if not replies:
                return web.Response(status=202, headers=headers)
            return web.json_response(replies, headers=headers)

        reply = await self.mcp.handle(payload)
        if reply is None:
            # Notification: the protocol requires a 202 with no body.
            return web.Response(status=202, headers=headers)
        return web.json_response(reply, headers=headers)

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Server→client SSE stream.

        We emit nothing on it for now (all our responses go out on the POST) but the stream
        must exist: a client that receives a 405 here often considers the connection broken.
        The heartbeats keep it from timing out.
        """
        response = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-store",
                "Connection": "keep-alive",
            }
        )
        await response.prepare(request)
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                await response.write(b": keep-alive\n\n")
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        return response

    async def delete(self, request: web.Request) -> web.Response:
        self.mcp.end_session(request.headers.get(SESSION_HEADER))
        return web.Response(status=204)
