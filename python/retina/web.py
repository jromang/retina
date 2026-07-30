"""Entry point of the web shell: ``python -m retina.web``.

**Python is the host.** The Python process starts, mounts the server, then launches the
native window (``retina_shell``) pointed at it. This inversion — compared with a native shell
that would embed Python — preserves the project's two pillars: the console lives in the same
process as ``app`` (console completeness), and the windowless mode stays trivial (a server on
a remote machine, a UI in a browser on the laptop).

Usage:
    python -m retina.web                # server + native window (MCP mounted on /mcp)
    python -m retina.web m31.retina     # opens a project at startup
    python -m retina.web --no-shell     # server only, the URL is opened by hand
    python -m retina.web --dev          # window pointed at the Vite server (HMR)
    python -m retina.web --mcp          # prints the MCP config for an external agent
    python -m retina.web --no-mcp       # turns off /mcp (built-in assistant included)

# Where to place the opening of a project at startup

**After ``site.start()``**, never before. ``Broadcaster.post`` plainly drops notifications as
long as ``bind_loop`` has not been called — which only happens when the aiohttp application
starts. A project opened earlier would therefore emit its ``restore_documents`` into the
void. That is not a problem for the domain state, which the first ``hello`` carries in its
snapshot anyway; it is one for everything that goes through a notification.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_ORIGIN = "http://localhost:5173"


def _configure_console() -> None:
    """The Windows console is cp1252: a "→" in a message would kill the process."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def find_shell() -> Path | None:
    """Locate the native shell's executable.

    Three locations, from the most specific to the most general: next to the package
    (application packaged by briefcase), then the Cargo release and debug targets
    (development).
    """
    name = "retina_shell.exe" if os.name == "nt" else "retina_shell"
    candidates = [
        Path(__file__).resolve().parent / "shell" / name,
        _REPO_ROOT / "target" / "release" / name,
        _REPO_ROOT / "target" / "debug" / name,
    ]
    return next((p for p in candidates if p.is_file()), None)


def find_icon() -> Path | None:
    """The window's icon. The shell does not know where the package lives — we do."""
    icon = Path(__file__).resolve().parent / "resources" / "branding" / "retina.ico"
    return icon if icon.is_file() else None


def _launch_shell(url: str, title: str) -> subprocess.Popen | None:
    exe = find_shell()
    if exe is None:
        print(
            "[retina] native shell not found — build it:\n"
            "    cargo build --release -p retina_shell\n"
            f"[retina] in the meantime, open: {url}",
            flush=True,
        )
        return None
    print(f"[retina] shell   : {exe.name}", flush=True)
    command = [str(exe), url, "--title", title]
    icon = find_icon()
    if icon is not None:
        command += ["--icon", str(icon)]
    return subprocess.Popen(command)


def _reopen_choice(app, args: argparse.Namespace) -> bool:
    """``--restore-session`` / ``--no-restore-session``, otherwise the persisted setting."""
    if args.restore_session is not None:
        return bool(args.restore_session)
    return app.session.reopen_enabled()


def _restore_session(app, args: argparse.Namespace) -> None:
    """Open the requested project, or the previous session if the option is enabled.

    Synchronous and blocking, unlike the RPC path which goes through a job: here nobody is
    waiting on the interface, and a client connecting during the load would see a half-filled
    snapshot. A failure does not prevent startup — an unreadable project is no reason to
    refuse the application.
    """
    target = args.project
    if target is None and _reopen_choice(app, args) and app.session.has_autosession():
        target = app.session.autosession_path()
    if not target:
        return
    try:
        report = app.open_project(target)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[retina] project not opened ({target}): {exc}", flush=True)
        return
    print(f"[retina] project : {report.path} ({len(report.windows)} window(s))", flush=True)
    for path in report.scripts_missing:
        print(f"[retina]   ! script not found: {path}", flush=True)
    for path in report.scripts_changed:
        print(f"[retina]   ! script modified since it was saved: {path}", flush=True)


def _save_session(app, args: argparse.Namespace) -> None:
    """Save the implicit session on close, if the option is enabled.

    With no client connected at that stage — the window has just been closed: we rewrite the
    document blob the client deposited along the way (a spontaneous
    ``project.store_documents``), and that is precisely why that deposit exists.
    """
    if not _reopen_choice(app, args) or not app.windows:
        return
    target = app.session.autosession_path()
    try:
        app.save_project(target)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[retina] session not saved: {exc}", flush=True)
        return
    print(f"[retina] session saved: {target}", flush=True)


def _print_mcp_config(port: int) -> None:
    """Print the configuration to paste into an MCP client.

    The token is the **persistent** one (``config_dir()/mcp-token``), not the session's:
    that is the whole point, a configuration file written once keeps working at the next
    launch.
    """
    import json

    from .server.security import mcp_token

    config = {
        "mcpServers": {
            "retina": {
                "type": "http",
                "url": f"http://127.0.0.1:{port}/mcp",
                "headers": {"X-Retina-Token": mcp_token()},
            }
        }
    }
    print("[retina] MCP     : /mcp active — client configuration:", flush=True)
    print(json.dumps(config, indent=2), flush=True)


async def _serve(args: argparse.Namespace) -> int:
    from aiohttp import web as aioweb

    from .process.registry import load_builtin
    from .server.core import ServerApp

    load_builtin()

    from .app import app as retina_app

    server = ServerApp(
        retina_app,
        port=args.port,
        token=args.token,
        dev_origin=DEV_ORIGIN if args.dev else None,
        mcp=args.mcp,
    )
    server.attach()

    runner = aioweb.AppRunner(server.aio, access_log=None)
    await runner.setup()
    site = aioweb.TCPSite(runner, "127.0.0.1", args.port)
    await site.start()

    # port 0 = "pick one": we read back the one that was assigned
    actual = server.port
    for sock in site._server.sockets or ():  # type: ignore[attr-defined]
        actual = sock.getsockname()[1]
    server.port = actual

    _restore_session(retina_app, args)

    url = server.url(DEV_ORIGIN if args.dev else f"http://127.0.0.1:{actual}")
    print(f"[retina] server  : http://127.0.0.1:{actual}", flush=True)
    print(f"[retina] url     : {url}", flush=True)
    if args.mcp and args.print_mcp:
        _print_mcp_config(actual)

    proc: subprocess.Popen | None = None
    if not args.no_shell:
        proc = _launch_shell(url, "Retina")

    stop = asyncio.Event()

    async def watch_shell() -> None:
        """Closing the window stops the server — otherwise Python would be left orphaned."""
        assert proc is not None
        while proc.poll() is None:
            await asyncio.sleep(0.25)
        print("[retina] window closed.", flush=True)
        stop.set()

    watcher = asyncio.create_task(watch_shell()) if proc is not None else None
    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if watcher is not None:
            watcher.cancel()
        if proc is not None and proc.poll() is None:
            proc.terminate()
        _save_session(retina_app, args)
        await runner.cleanup()
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    ap = argparse.ArgumentParser(prog="retina.web", description="Retina web shell")
    ap.add_argument("project", nargs="?", help="a .retina project to open at startup")
    ap.add_argument("--port", type=int, default=8765, help="listening port (0 = automatic)")
    ap.add_argument("--no-shell", action="store_true", help="server only, no native window")
    # /mcp is mounted by default: the built-in assistant (the chat panel) depends on it, and
    # the security posture does not change — loopback + token are still required, and the
    # persistent token opens only that route. The deliberate act has moved: it is typing in
    # the chat, or pasting the config (printed only with --mcp) into an external agent.
    ap.add_argument(
        "--no-mcp",
        dest="mcp",
        action="store_false",
        help="does not mount /mcp — the built-in assistant and external agents are cut off",
    )
    ap.add_argument(
        "--mcp",
        dest="print_mcp",
        action="store_true",
        help="prints the MCP configuration to paste into an external agent (Claude Code…)",
    )
    ap.set_defaults(mcp=True)
    ap.add_argument(
        "--dev",
        action="store_true",
        help=f"points the window at the Vite server ({DEV_ORIGIN}) instead of the built assets",
    )
    ap.add_argument(
        "--token",
        help=(
            "a fixed session token instead of a random one. Reserved for end-to-end tests, "
            "which must know the URL before launching the server — do not use otherwise."
        ),
    )
    ap.add_argument(
        "--restore-session",
        dest="restore_session",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "reopens the previous session at startup and saves it on close. Without the "
            "option, we follow the persisted setting (disabled by default: writing every "
            "history state can take a while, and that must not come as a surprise)."
        ),
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(name)s] %(message)s",
    )

    try:
        return asyncio.run(_serve(args))
    except KeyboardInterrupt:
        print("\n[retina] stopped.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
