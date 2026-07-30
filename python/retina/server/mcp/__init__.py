"""MCP server — Retina exposed to an agent (Claude Code, Claude Desktop…).

The *Model Context Protocol* is JSON-RPC 2.0: an agent discovers **tools** (``tools/list``),
calls them (``tools/call``), reads **resources** and **prompts**. This package implements its
server side, over two transports (HTTP in the web shell, stdio in headless), on top of a
**transport-agnostic tool registry** (:mod:`~retina.server.mcp.tools`).

# Why the registry is separate from the transport

An integrated chat panel will not need MCP: it will run in the same process and call the
registry directly. Separating the two avoids ending up one day with two definitions of the
same tool — one for the external agent, the other for the internal one — which would diverge
at the first addition.

# Why this package lives under ``server/``

Because MCP is a **client of the API** on the same footing as the web shell or the console,
and the domain must know nothing about it (``import retina`` must pull in neither aiohttp
nor MCP — cf. ``tests/server/test_headless_parity.py``).
"""

from __future__ import annotations

__all__ = ["PROTOCOL_VERSION", "SERVER_INFO"]

#: Version of the MCP protocol we announce in ``initialize``. The client proposes its own; we
#: return this one, and a more recent client knows how to fall back.
PROTOCOL_VERSION = "2025-06-18"

SERVER_INFO = {"name": "retina", "title": "Retina", "version": "0.1.0"}
