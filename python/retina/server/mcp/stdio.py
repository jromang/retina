"""stdio transport — an MCP server without a shell, launched by the client itself.

This is the mode of Claude Desktop and of agent launchers: the client starts the process and
talks JSON-RPC to it line by line over stdin/stdout. No token — whoever launched the process
already owns it, and adding one would be a ritual with no boundary to defend.

# A ``ServerApp`` without a TCP site

We build the complete server (console, jobs, snapshots, tool registry) but **without** opening
a port. Everything works, except that the ``Broadcaster``, having no bound loop, throws its
notifications away: nobody is listening to them, and that is exactly the case ``bind_loop``
provides for.

# stdout belongs to the protocol

The console redirects stdout while a cell runs, and a ``print`` from a user script would land
in the middle of a JSON-RPC response — corrupting the stream. We therefore write the responses
to the **original descriptor**, captured at startup before anyone could have replaced it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from ..core import ServerApp


async def serve(
    server: ServerApp, stdin: TextIO | None = None, stdout: TextIO | None = None
) -> int:
    """Read loop stdin → dispatch → stdout. Returns 0 when the stream closes."""
    from .protocol import McpServer

    mcp = McpServer(server)
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    loop = asyncio.get_running_loop()

    while True:
        # Blocking read offloaded: `asyncio.connect_read_pipe` does not work on Windows
        # pipes, and the throughput here is a handful of messages per second.
        line = await loop.run_in_executor(None, source.readline)
        if not line:
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(sink, {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32700, "message": "invalid JSON"}})
            continue
        reply = await mcp.handle(message)
        if reply is not None:
            _write(sink, reply)


def _write(sink: TextIO, payload: dict) -> None:
    sink.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sink.flush()
