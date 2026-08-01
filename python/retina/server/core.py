"""``ServerApp`` — the web shell, mounted on a :class:`~retina.app.Application` instance.

It *wires* the domain's attachment points (echo, window changes, viewport) and unwires them
on shutdown. It contains no business logic — everything goes through ``app.*``, which
produces its Python echo.

The ``Application`` is **injected**, never taken from the singleton: that is what lets the
tests mount a server on fresh state (``ServerApp(Application())``). Only ``retina.web``
passes the singleton.

# Threading model

The asyncio loop plays the role of the UI thread: RPC calls, being short, run on it directly.
Everything long — pixel conversion to float16 today, process execution tomorrow — goes into a
``ThreadPoolExecutor``, exactly like a thread pool. The return path toward the clients then
goes through the :class:`~retina.server.broadcast.Broadcaster`, which republishes on the
loop: the literal transposition of the "a worker never touches a widget" rule.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import WSMsgType, web

from ..io import format_groups as io_formats
from .broadcast import Broadcaster
from .chat import ChatService
from .console import Console
from .docs import DocHandlers
from .handlers_app import APP_METHODS, AppHandlers
from .handlers_chat import CHAT_METHODS, ChatHandlers
from .handlers_console import CONSOLE_METHODS, ConsoleHandlers
from .handlers_credits import CREDIT_METHODS, CreditHandlers
from .handlers_fs import FS_METHODS, FsHandlers
from .handlers_layout import LAYOUT_METHODS, LayoutHandlers
from .handlers_library import LIBRARY_METHODS, LibraryHandlers
from .handlers_notifications import NOTIFICATION_METHODS, NotificationHandlers
from .handlers_pipeline import PIPELINE_METHODS, PipelineHandlers
from .handlers_preferences import PREFERENCE_METHODS, PreferenceHandlers
from .handlers_process import PROCESS_METHODS, ProcessHandlers
from .handlers_project import PROJECT_METHODS, ProjectHandlers, ProjectService
from .handlers_stats import STATS_METHODS, StatsHandlers
from .jobs import JobRunner
from .layout_backend import WebLayoutBackend
from .pixels import RUN_ID, PixelService, stream_buffer
from .rpc import Dispatcher, current_connection
from .rtp import RTP_METHODS, RtpHandlers, RtpService
from .security import local_origins, make_auth_middleware, mcp_token, new_token
from .state import SnapshotBuilder

if TYPE_CHECKING:
    from ..app import Application
    from ..model.window import ImageWindow

log = logging.getLogger("retina.server")

#: Frontend assets built by Vite (``npm run build`` in ``web/``). Absent from a freshly
#: cloned repository — the server says so clearly rather than returning a bare 404.
WEBUI_DIR = Path(__file__).resolve().parent.parent / "resources" / "webui"

PROTOCOL_VERSION = 1


class ServerApp:
    """aiohttp server exposing ``app`` to a web frontend."""

    def __init__(
        self,
        app: Application,
        *,
        port: int = 8765,
        token: str | None = None,
        dev_origin: str | None = None,
        max_workers: int | None = None,
        mcp: bool = False,
    ) -> None:
        self.app = app
        self.port = port
        self.token = token or new_token()
        self.dev_origin = dev_origin
        self._attached = False
        self._next_connection = 0
        #: Secondary listeners of the Python echo and of the console output. The broadcast
        #: is still served first; these lists exist so that a caller *outside the WebSocket
        #: clients* — the MCP server — can pick up what an action produced. They are called
        #: from worker threads: see ``_on_domain_echo``.
        self.echo_listeners: list[Callable[[str], None]] = []
        self.stream_listeners: list[Callable[[str, str], None]] = []

        self.snapshots = SnapshotBuilder(app)
        self.broadcast = Broadcaster(self.snapshots.build)
        # The pool is built once: the preference therefore means "at the next launch",
        # which is what its tooltip says. A caller that passes an explicit value (the
        # tests) keeps control.
        if max_workers is None:
            max_workers = int(app.preferences.get("performance.max_workers"))
        self.jobs = ThreadPoolExecutor(max_workers=max_workers,
                                       thread_name_prefix="retina-job")
        self.pixels = PixelService(app, self.snapshots, self.jobs)
        self.runner = JobRunner(
            app,
            self.jobs,
            self.broadcast.notify,
            self.broadcast.mark_state_dirty,
        )
        self.snapshots.jobs_provider = self.runner.active

        self.layout = WebLayoutBackend(self.broadcast)
        self.console = Console(app, self._on_console_stream)
        self.rtp = RtpService(app, self.jobs, self.broadcast.notify)
        self.docs = DocHandlers()
        # MCP server: **opt-in**. Enabling it gives an agent the Python console and
        # everything it reaches — that must be a deliberate gesture, not a default.
        self.mcp: Any = None
        if mcp:
            from .mcp.protocol import McpEndpoint

            self.mcp = McpEndpoint(self)
        # The built-in assistant: its engine (the user's claude CLI) acts on the session
        # through `/mcp` — without an endpoint, `chat.send` refuses cleanly.
        self.chat = ChatService(self)

        self.rpc = Dispatcher(on_mutation=self.broadcast.mark_state_dirty)
        self.handlers = AppHandlers(app, self.snapshots)
        self.layout_handlers = LayoutHandlers(app, self.layout)
        self.notification_handlers = NotificationHandlers(app)
        self.process_handlers = ProcessHandlers(self.runner)
        self.pipeline_handlers = PipelineHandlers(app, self.runner, self.jobs)
        self.projects = ProjectService(app, self.broadcast)
        self.project_handlers = ProjectHandlers(app, self.runner, self.projects)
        self.console_handlers = ConsoleHandlers(self.console)
        self.library_handlers = LibraryHandlers(app)
        self.fs_handlers = FsHandlers()
        self.stats_handlers = StatsHandlers(app, self.snapshots, self.jobs)
        self.rtp_handlers = RtpHandlers(self.rtp)
        self.rpc.register_all(self.handlers, APP_METHODS)
        self.rpc.register_all(self.layout_handlers, LAYOUT_METHODS)
        self.preference_handlers = PreferenceHandlers(app)
        self.rpc.register_all(self.notification_handlers, NOTIFICATION_METHODS)
        self.rpc.register_all(self.preference_handlers, PREFERENCE_METHODS)
        self.credit_handlers = CreditHandlers()
        self.rpc.register_all(self.credit_handlers, CREDIT_METHODS)
        self.rpc.register_all(self.process_handlers, PROCESS_METHODS)
        self.rpc.register_all(self.pipeline_handlers, PIPELINE_METHODS)
        self.rpc.register_all(self.project_handlers, PROJECT_METHODS)
        self.rpc.register_all(self.console_handlers, CONSOLE_METHODS)
        self.rpc.register_all(self.library_handlers, LIBRARY_METHODS)
        self.rpc.register_all(self.fs_handlers, FS_METHODS)
        self.rpc.register_all(self.stats_handlers, STATS_METHODS)
        self.rpc.register_all(self.rtp_handlers, RTP_METHODS)
        self.chat_handlers = ChatHandlers(self.chat)
        self.rpc.register_all(self.chat_handlers, CHAT_METHODS)
        self.rpc.register("hello", self._hello)
        self.rpc.register("rpc.methods", self.rpc.methods)

        extra = (dev_origin,) if dev_origin else ()
        self.aio = web.Application(
            middlewares=[
                make_auth_middleware(
                    self.token,
                    local_origins(port, extra),
                    # The session token is drawn at every launch: an `.mcp.json` written
                    # once could never carry it. Hence a second, persistent token, accepted
                    # on the `/mcp` route alone.
                    mcp_token=mcp_token() if mcp else None,
                )
            ]
        )
        self._add_routes()
        self.aio.on_startup.append(self._on_startup)
        self.aio.on_shutdown.append(self._on_shutdown)

    # --- routes ---------------------------------------------------------------
    def _add_routes(self) -> None:
        router = self.aio.router
        router.add_get("/api/ping", self._ping)
        router.add_get("/api/pixels/{view_id}.f16", self.pixels.handle_view)
        router.add_get("/api/mask/{window_id}.f16", self.pixels.handle_mask)
        router.add_get("/api/rtp.f16", self._rtp_pixels)
        if self.mcp is not None:
            self.mcp.add_routes(router)
        self.docs.add_routes(router)
        router.add_get("/ws", self._websocket)
        router.add_get("/", self._index)
        router.add_get("/favicon.png", self._favicon)
        if WEBUI_DIR.is_dir():
            router.add_static("/assets", WEBUI_DIR / "assets", name="assets")

    async def _rtp_pixels(self, request: web.Request) -> web.StreamResponse:
        """Last real-time preview. A stale generation answers 409, like the pixels."""
        try:
            generation = int(request.query.get("gen", "0"))
        except ValueError:
            raise web.HTTPBadRequest(text="invalid gen") from None
        found = self.rtp.buffer_for(generation)
        if found is None:
            raise web.HTTPConflict(text="stale preview")
        buffer, info = found
        return await stream_buffer(request, buffer, info["width"], info["height"],
                                   info["channels"], identity=f"rtp:{generation}")

    async def _ping(self, request: web.Request) -> web.Response:
        """Public probe: says the server is up, and which language it speaks.

        The language is here, and **not only in the ``hello``**, because it is needed *before
        the first render*: the frontend's label tables are built when their module is
        imported, and the ``hello`` arrives afterwards. The client otherwise asked for it too
        late and had to reload the page to correct itself — a systematic reload as soon as
        browser and server disagree, which is the common case (browser in English, machine in
        French).

        This field does not meaningfully widen the public surface: the server's locale is
        already readable in the headers it returns, and this route is deliberately the only
        one that answers without a token — that is what lets `--no-shell` say "I am ready".
        """
        return web.json_response({
            "service": "retina",
            "protocol": PROTOCOL_VERSION,
            "language": self.app.language,
        })

    async def _index(self, request: web.Request) -> web.Response:
        index = WEBUI_DIR / "index.html"
        if not index.is_file():
            raise web.HTTPServiceUnavailable(
                text=(
                    "Frontend missing. Build it:\n"
                    "    cd web && npm install && npm run build\n"
                    "or start the Vite development server with `--dev`."
                ),
                content_type="text/plain",
            )
        return web.Response(body=index.read_bytes(), content_type="text/html", charset="utf-8")

    async def _favicon(self, request: web.Request) -> web.FileResponse:
        """The application logo — browser tab *and* corner of the title bar.

        An explicit route rather than a static mount of the ``webui`` root: mounting ``/``
        would capture everything not already routed, `/api` included if the order ever
        changed. Vite's ``web/public`` folder contains only this file; the day it contains
        others, that will be the occasion for a real mount, under a prefix of its own.
        """
        icon = WEBUI_DIR / "favicon.png"
        if not icon.is_file():
            raise web.HTTPNotFound(text="favicon missing — run scripts/gen_icons.py")
        return web.FileResponse(icon, headers={"Cache-Control": "public, max-age=86400"})

    # --- RPC ------------------------------------------------------------------
    def _hello(self) -> dict:
        """Handshake: protocol version and full initial snapshot."""
        return {
            "protocol": PROTOCOL_VERSION,
            # The client needs to know its own identity to recognize, in
            # `viewport.changed`, the echoes of its own gestures — which it has already
            # applied locally — and not replay them.
            "connection": current_connection.get(),
            # Identifier of THIS process. The client glues it to the pixel addresses:
            # without it, `/api/pixels/Image01.f16?gen=1` would designate a different image
            # in every session while keeping the same address — and the WebView2 disk cache,
            # which survives restarts, replayed the previous one's pixels (black viewport).
            "run": RUN_ID,
            "snapshot": self.snapshots.build(),
            # The client adopts this layout instead of imposing its defaults: a script that
            # set the layout before the interface opened must be respected.
            "layout": self.layout.state(),
            # Recents, reopening, current project — and the document blob if a project was
            # opened **without** a client (startup with a `.retina`, restored session):
            # there was then nobody to receive `restore_documents`.
            "session": self._session_state(),
            "methods": sorted(self.rpc.methods()),
            # File extensions by group, from the domain's single dispatch point. The client
            # builds its file dialogs and its "this format quantizes" warning from this
            # rather than from a list of its own, which would drift at the first format
            # added.
            "formats": io_formats(),
        }

    def _session_state(self) -> dict:
        state = dict(self.app.session.state())
        state["project"] = self.app.project_path
        # Documents go out **only if a project is open**. The client deposits its blob
        # spontaneously during the session (that is what keeps the closing save fresh);
        # without this guard, a browser connecting afterwards would be handed the tabs of a
        # session it does not belong to, and its own state would be replaced on the first
        # `hello`.
        documents = self.app.project_documents()
        if self.app.project_path is not None and documents is not None:
            state["documents"] = documents
        return state

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        self._next_connection += 1
        connection = f"c{self._next_connection}"
        self.broadcast.add(ws)
        await self.broadcast.flush_pending(ws)
        log.info("client %s connected (%d active)", connection, self.broadcast.client_count)
        # One task per message, instead of an inline `await`. Without that, a long request
        # (`console.execute` on a script running for minutes) monopolizes the read loop: no
        # further message from that connection is handled — not even the `console.interrupt`
        # meant to stop the script, nor a simple viewport pan. JSON-RPC pairs requests and
        # responses by `id`, so interleaving is legitimate.
        inflight: set[asyncio.Task] = set()
        try:
            async for msg in ws:
                if msg.type is WSMsgType.TEXT:
                    task = asyncio.create_task(self._on_message(ws, msg.data, connection))
                    inflight.add(task)
                    task.add_done_callback(inflight.discard)
                elif msg.type is WSMsgType.ERROR:
                    log.warning("websocket in error: %s", ws.exception())
        finally:
            for task in inflight:
                task.cancel()
            self.broadcast.discard(ws)
            log.info("client %s disconnected (%d remaining)", connection,
                     self.broadcast.client_count)
        return ws

    async def _on_message(self, ws: web.WebSocketResponse, raw: str, connection: str) -> None:
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_json(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "invalid JSON"}}
            )
            return
        response = await self.rpc.dispatch(request, connection)
        if response is not None:
            await ws.send_json(response)

    # --- life cycle -----------------------------------------------------------
    async def _on_startup(self, _aio: web.Application) -> None:
        self.broadcast.bind_loop(asyncio.get_running_loop())

    async def _on_shutdown(self, _aio: web.Application) -> None:
        for ws in list(self.broadcast._sockets):
            await ws.close(code=1001, message=b"server shutting down")
        self.detach()
        await self.chat.shutdown()
        self.console.shutdown()
        self.jobs.shutdown(wait=False, cancel_futures=True)

    def attach(self) -> None:
        """Wire the domain's attachment points (symmetric with :meth:`detach`)."""
        if self._attached:
            return
        self.app.on_echo = self._on_domain_echo
        self.app.on_windows_changed = self._on_windows_changed
        # A process can be born mid-session (console, assistant, `load_user`): the client's
        # catalogue — requested once per session — must learn about it.
        from ..process import registry

        registry.on_changed = self._on_process_registered
        # The library is not in the snapshot (it lives on disk, not in memory): we warn, the
        # client re-reads.
        self.app.library.on_changed = self._on_library_changed
        # Same reason as the library: the recents live on disk, not in the snapshot. We
        # warn, the client re-reads.
        self.app.session.on_changed = self._on_session_changed
        # The preferences live on disk, not in the snapshot: we warn, the client re-reads.
        # Same mechanics as the library and the recents.
        self.app.preferences.on_changed = self._on_preferences_changed
        self.app.notifications.on_changed = self._on_notification
        self.app.layout._attach(self.layout)
        self._bind_viewports()
        self._attached = True

    def detach(self) -> None:
        """Return the domain to its neutral state — essential for tests to chain."""
        if not self._attached:
            return
        self.app.on_echo = None
        self.app.on_windows_changed = None
        from ..process import registry

        registry.on_changed = None
        self.app.library.on_changed = None
        self.app.session.on_changed = None
        self.app.preferences.on_changed = None
        self.app.notifications.on_changed = None
        for win in self.app.windows:
            win.viewport.on_change = None
        self.app.layout._attach(None)
        self._attached = False

    # --- domain hooks ---------------------------------------------------------
    def _on_console_stream(self, name: str, text: str) -> None:
        """A script's standard output, relayed while it runs.

        Emitted from the console thread: ``notify`` republishes onto the loop.
        """
        self.broadcast.notify("console.stream", {"name": name, "text": text})
        for listener in list(self.stream_listeners):
            listener(name, text)

    def _on_domain_echo(self, code: str) -> None:
        """The Python echo of every action, as the console displays it.

        Callable from a worker thread: ``notify`` republishes onto the loop.

        The fan-out is done on a **copy** of the list: listeners add and remove themselves
        from the loop (for the duration of an MCP tool call) while the echo itself arrives
        from a job thread.
        """
        self.broadcast.notify("echo", {"code": code})
        for listener in list(self.echo_listeners):
            listener(code)

    def _on_library_changed(self) -> None:
        self.broadcast.notify("library.changed", {})

    def _on_process_registered(self) -> None:
        """A process has just been registered — the client will re-read ``process.list``.

        Callable from the console thread (a ``@register`` typed at the prompt):
        ``notify`` republishes onto the loop.
        """
        self.broadcast.notify("process.changed", {})

    def _on_notification(self, event: str, payload: dict) -> None:
        """Relay from the notification center, callable from a worker.

        ``notify`` and ``mark_state_dirty`` both go back through the loop: that is what makes
        the hook safe when ``add`` comes from a job thread. The snapshot is dirtied so that
        rehydration (hello, reconnection) finds the center again.
        """
        self.broadcast.notify(f"notification.{event}", payload)
        self.broadcast.mark_state_dirty()

    def _on_session_changed(self) -> None:
        self.broadcast.notify("session.changed", {})

    def _on_preferences_changed(self) -> None:
        self.broadcast.notify("preferences.changed", {})

    def _on_windows_changed(self) -> None:
        self._bind_viewports()
        self.broadcast.mark_state_dirty()

    def _bind_viewports(self) -> None:
        """(Re)hook the viewport observer on every window.

        ``ViewportState.on_change`` has **only one** slot, and a window created after startup
        has none: hence this pass on every change to the window list.
        """
        for win in self.app.windows:
            if win.viewport.on_change is None:
                win.viewport.on_change = self._make_viewport_observer(win)

    def _make_viewport_observer(self, win: ImageWindow):
        def observer() -> None:
            # `origin` lets the client that authored the gesture ignore the echo of its own
            # pan: it has already moved its camera locally. The other clients — and the
            # console, which has no origin — apply it.
            self.broadcast.notify(
                "viewport.changed",
                {
                    "window": win.id,
                    "viewport": SnapshotBuilder._viewport(win),
                    "origin": current_connection.get(),
                },
            )

        return observer

    # --- URL ------------------------------------------------------------------
    def url(self, base: str | None = None) -> str:
        """Opening URL, token included. ``base`` allows targeting the Vite server in dev."""
        base = base or f"http://127.0.0.1:{self.port}"
        return f"{base}/?t={self.token}"


def create_app(app: Application | None = None, **kwargs) -> ServerApp:
    """Build the server. With no argument, takes the application singleton."""
    if app is None:
        from ..app import app as singleton

        app = singleton
    return ServerApp(app, **kwargs)
