"""Local authentication for the web server.

The server listens on the loopback and drives the *whole* application: opening files, running
arbitrary Python through the console. Without a guard, any web page open in the browser could
talk to it (loopback is not a security boundary on the browser side: that is the "DNS
rebinding" attack). Hence two protections, both necessary:

1. **A token** drawn at startup, passed in the initial URL. A third-party page does not know
   it. It is accepted in three forms, each for a precise use case:
   - cookie ``retina_token`` — the only way for requests the *browser* issues on its own
     (``<script src>``, ``<link href>``);
   - header ``X-Retina-Token`` — used by the frontend code (``fetch``); works through the Vite
     proxy in development, where the cookie would not follow (different origin);
   - parameter ``?t=`` — for the initial URL and for the WebSocket, whose browser API allows
     no custom header.

2. **An ``Origin`` check** on the WebSocket. The token alone would not be enough: a malicious
   page that had guessed or leaked it could open a cross-origin WS (WebSockets are not subject
   to the same-origin policy).
"""

from __future__ import annotations

import contextlib
import secrets
import stat
from collections.abc import Awaitable, Callable

from aiohttp import web

COOKIE_NAME = "retina_token"
HEADER_NAME = "X-Retina-Token"
QUERY_NAME = "t"

#: Routes served without a token. ``/api/ping`` lets a launcher script know the server is up
#: without knowing anything about the session (it discloses no data).
PUBLIC_PATHS = frozenset({"/api/ping"})

#: Route of the MCP server — the only one the persistent token opens.
MCP_PATH = "/mcp"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def mcp_token() -> str:
    """**Persistent** token of the MCP server, created on first use.

    The session token is drawn at every launch: perfect for a URL the server passes to its
    own window, unusable in an agent configuration file written once and for all. This one
    lives in the configuration directory, readable by its owner only, and opens **only**
    ``/mcp`` — it therefore gives access to neither the pixels nor the session's WebSocket.
    """
    from ..paths import config_dir

    path = config_dir() / "mcp-token"
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = new_token()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    # File systems without POSIX permissions (FAT, some Windows mounts): the token stays
    # usable, simply less protected than on a Unix machine.
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return token


def _presented_token(request: web.Request) -> str | None:
    return (
        request.headers.get(HEADER_NAME)
        or request.query.get(QUERY_NAME)
        or request.cookies.get(COOKIE_NAME)
    )


def make_auth_middleware(
    token: str, allowed_origins: frozenset[str], mcp_token: str | None = None
):
    """Middleware checking the token + the ``Origin`` of WebSockets.

    ``mcp_token``, if supplied, is a second secret accepted **on the ``/mcp`` route only**:
    see :func:`mcp_token`.
    """

    @web.middleware
    async def auth_middleware(
        request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        if request.path in PUBLIC_PATHS:
            return await handler(request)

        presented = _presented_token(request)
        # constant-time comparison: the token is a secret
        accepted = presented is not None and secrets.compare_digest(presented, token)
        via_mcp = False
        if not accepted and mcp_token is not None and request.path == MCP_PATH:
            via_mcp = presented is not None and secrets.compare_digest(presented, mcp_token)
            accepted = via_mcp
        if not accepted:
            raise web.HTTPUnauthorized(text="invalid or missing token")

        # WebSockets escape the same-origin policy: this is the only place where the Origin
        # must be checked explicitly.
        if request.path == "/ws":
            origin = request.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                raise web.HTTPForbidden(text=f"origin refused: {origin}")

        response = await handler(request)
        # Sets the cookie as soon as the token arrived some other way: the subsequent requests
        # issued by the browser itself (assets) have no other way to authenticate.
        #
        # `prepared` rules out responses already on the wire — the pixels are served as a
        # stream, their headers are sent before this code runs, and `set_cookie` would raise
        # there. Those requests come from the frontend code, which already carries the header.
        #
        # A request authenticated by the **MCP token** is not entitled to it: setting the
        # session cookie on it would give it the whole server, exactly what this second token,
        # bounded to `/mcp`, is meant to avoid.
        if via_mcp:
            return response
        if not response.prepared and request.cookies.get(COOKIE_NAME) != token:
            response.set_cookie(
                COOKIE_NAME,
                token,
                httponly=True,
                samesite="Strict",
                path="/",
            )
        return response

    return auth_middleware


def local_origins(port: int, extra: tuple[str, ...] = ()) -> frozenset[str]:
    """Allowed origins: ours under both spellings, plus the Vite server in dev."""
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    origins.update(extra)
    return frozenset(origins)
