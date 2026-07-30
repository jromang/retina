"""Entry point of the MCP server in stdio mode: ``python -m retina.mcp``.

For a client that launches the process itself (Claude Desktop, an agent launcher) and has no
Retina interface open. The counterpart attached to a live session is
``python -m retina.web --mcp``, which exposes the **same** tool surface over HTTP — and that
is the one to prefer when the user is working in front of their screen, since the agent acts
there on the windows they have in view.

Client-side configuration:

    {"command": "python", "args": ["-m", "retina.mcp"]}
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="retina.mcp", description="Retina MCP server (stdio, no interface)"
    )
    ap.add_argument("project", nargs="?", help="a .retina project to open at startup")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    # The logs go to **stderr**: stdout is the protocol's channel.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="[%(name)s] %(message)s",
        stream=sys.stderr,
    )

    from .process.registry import load_builtin

    load_builtin()

    from .app import app as retina_app
    from .server.core import ServerApp
    from .server.mcp.stdio import serve

    if args.project:
        retina_app.open_project(args.project)

    # `mcp=False`: the transport here is stdio, there is no HTTP route to mount — and no
    # persistent token to create for a channel the client already owns.
    server = ServerApp(retina_app, port=0)
    server.attach()
    try:
        return asyncio.run(serve(server))
    except KeyboardInterrupt:
        return 0
    finally:
        server.detach()
        server.console.shutdown()
        server.jobs.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    raise SystemExit(main())
