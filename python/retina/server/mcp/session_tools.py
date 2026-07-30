"""MCP tools that act on the session: files, views, processes, history, console.

Every function delegates to an existing handler (``AppHandlers``, ``ProcessHandlers``,
``StatsHandlers``, ``ProjectHandlers``, ``Console``) or to ``app`` directly. Long processes go
through the server's ``JobRunner``, like the web shell: the agent thereby inherits cooperative
cancellation and progress, without a second execution path existing.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .tools import (
    ImageResult,
    Tool,
    ToolError,
    _bool,
    _int,
    _schema,
    _str,
    _StreamCollector,
)

if TYPE_CHECKING:
    from ..core import ServerApp
    from .tools import ToolRegistry


# --------------------------------------------------------------------------- #
# Shared helpers                                                               #
# --------------------------------------------------------------------------- #
async def await_job(server: ServerApp, job_id: str) -> dict:
    """Waits for a server job to finish without blocking the loop.

    ``JobRunner`` returns immediately (an integration takes hours and the interface must not
    freeze); an agent, on the other hand, most often wants the result. So we await the pool's
    ``Future`` — cancellation and progress remaining those of the job.
    """
    job = server.runner.get(job_id)
    if job is None:  # pragma: no cover — the id was just returned
        raise ToolError(f"Unknown job: {job_id!r}")
    if job.future is not None:
        await asyncio.wrap_future(job.future)
    return job.to_dict()


def view_digest(server: ServerApp, view_id: str | None) -> dict | None:
    """What one needs to know about a view after an action: where its history stands.

    ``pixel_gen`` is read **after** a ``build()``: the counter is only reevaluated when the
    snapshot is built, and reading it before would return the generation prior to the action.
    """
    if view_id is None:
        return None
    try:
        view = server.app.view(view_id)
    except KeyError:
        return None
    server.snapshots.build()
    return {
        "view": view.id,
        "history": view.history_labels(),
        "history_index": view.history_index,
        "can_undo": view.can_go_backward,
        "can_redo": view.can_go_forward,
        "pixel_gen": server.snapshots.pixel_gen(view.id),
    }


def _target_view(server: ServerApp, view: str | None) -> str | None:
    if view is not None:
        return view
    active = server.app.active_view
    return None if active is None else active.id


def compact_state(server: ServerApp) -> dict:
    """The snapshot, projected for an agent.

    We strip what only serves rendering (viewport, panel layout, links) and keep what
    describes the work: which images are open, where their history stands, what is running.
    That is the difference between a few hundred bytes and several kilobytes per call, on a
    tool the agent will call back constantly.
    """
    snapshot = server.snapshots.build()
    windows = []
    for win in snapshot["windows"]:
        views = []
        for entry in win["views"]:
            history = entry["history"]
            view: dict[str, Any] = {
                "view": entry["id"],
                "size": [entry["width"], entry["height"], entry["channels"]],
                "history": history["labels"],
                "history_index": history["index"],
                "stf_enabled": entry["stf"]["enabled"],
            }
            if entry["is_preview"]:
                view["preview_rect"] = entry["rect"]
            views.append(view)
        windows.append(
            {
                "window": win["id"],
                "file_path": win["file_path"],
                "modified": win["is_modified"],
                "has_wcs": win["has_wcs"],
                "fits_keywords": win["keyword_count"],
                "mask": None if win["mask"] is None else win["mask"]["enabled"],
                "views": views,
            }
        )
    return {
        "active_window": snapshot["active_window"],
        "active_view": snapshot["active_view"],
        "project": snapshot["project"],
        "windows": windows,
        "jobs": snapshot["jobs"],
        "notifications": [n["message"] for n in snapshot["notifications"][-3:]],
    }


# --------------------------------------------------------------------------- #
# Definitions                                                                  #
# --------------------------------------------------------------------------- #
def tools(registry: ToolRegistry) -> list[Tool]:
    server = registry.server

    # --- state --------------------------------------------------------------
    def get_state() -> dict:
        return compact_state(server)

    # --- files --------------------------------------------------------------
    def open_images(paths: list[str]) -> dict:
        opened = []
        for path in paths:
            opened.append(server.handlers.open(path))
        return {"windows": opened, "state": compact_state(server)}

    def save_image(path: str, window: str | None = None) -> dict:
        server.handlers.save(path, window)
        return {"saved": path}

    async def project(action: str, path: str | None = None) -> dict:
        if action == "close":
            server.project_handlers.close()
            return {"closed": True}
        if action == "save":
            reply = server.project_handlers.save(path)
        elif action == "open":
            if not path:
                raise ToolError("project(action='open') requires a path")
            reply = server.project_handlers.open(path)
        else:
            raise ToolError(f"Unknown action: {action!r} (open, save, close)")
        job = await await_job(server, reply["job"])
        return {"job": job, "project": server.app.project_path}

    # --- catalogue ----------------------------------------------------------
    def list_processes(category: str | None = None) -> dict:
        catalog = _catalog(registry)
        if category is not None:
            wanted = category.casefold()
            entries = [e for e in catalog if e["category"].casefold() == wanted]
            if not entries:
                known = sorted({e["category"] for e in catalog})
                raise ToolError(f"Unknown category: {category!r}. Known: {', '.join(known)}")
        else:
            entries = catalog
        return {"count": len(entries), "processes": entries}

    def describe_process(process_id: str) -> dict:
        from ...documentation import doc_markdown, has_doc
        from ...process.registry import get
        from ..handlers_process import _describe

        try:
            cls = get(process_id)
        except KeyError:
            raise ToolError(f"Unknown process: {process_id!r}") from None
        described = _describe(cls)
        # The documentation is in English: it is the msgid, and the agent reads a contract,
        # not an interface. `lang="en"` rather than the server's language, for that reason.
        if has_doc(process_id):
            described["documentation"] = doc_markdown(process_id, "en")
        return described

    # --- execution ----------------------------------------------------------
    async def apply_process(
        process_id: str,
        params: dict | None = None,
        view: str | None = None,
        wait: bool = True,
    ) -> dict:
        target = None if view is None else view
        reply = server.process_handlers.run(process_id, params or {}, target)
        job_id = reply["job"]
        if not wait:
            return {"job": job_id, "state": "queued"}
        job = await await_job(server, job_id)
        return _job_outcome(server, job, _target_view(server, target))

    async def apply_recipe(
        processes: list[dict], view: str | None = None, wait: bool = True
    ) -> dict:
        reply = server.process_handlers.run_container(processes, view)
        job_id = reply["job"]
        if not wait:
            return {"job": job_id, "state": "queued"}
        job = await await_job(server, job_id)
        return _job_outcome(server, job, _target_view(server, view))

    def history(action: str, view: str | None = None, index: int | None = None) -> dict:
        if view is not None:
            server.handlers.select_view(view)
        if action == "undo":
            done = server.handlers.undo()
        elif action == "redo":
            done = server.handlers.redo()
        elif action == "goto":
            if index is None:
                raise ToolError("history(action='goto') requires an index")
            done = server.handlers.go_to_history(int(index))
        else:
            raise ToolError(f"Unknown action: {action!r} (undo, redo, goto)")
        return {"applied": done, "view": view_digest(server, _target_view(server, view))}

    async def jobs(action: str = "list", job: str | None = None) -> dict:
        if action == "list":
            return {"jobs": server.runner.active()}
        if job is None:
            raise ToolError(f"jobs(action={action!r}) requires a job id")
        if action == "get":
            found = server.runner.get(job)
            if found is None:
                raise ToolError(f"Unknown job: {job!r}")
            return found.to_dict()
        if action == "cancel":
            return {"cancelled": server.process_handlers.cancel(job)}
        if action == "wait":
            return await await_job(server, job)
        raise ToolError(f"Unknown action: {action!r} (list, get, wait, cancel)")

    # --- measurement --------------------------------------------------------
    async def get_stats(
        view: str | None = None,
        bins: int = 64,
        x: float | None = None,
        y: float | None = None,
        n: int | None = None,
    ) -> dict:
        target = _target_view(server, view)
        if target is None:
            raise ToolError("No view to measure: open an image first")
        if x is not None and y is not None:
            probe = server.handlers.readout(x, y, n)
            return {"view": target, "readout": probe}
        return {"view": target, **await server.stats_handlers.histogram(target, bins)}

    # --- display ------------------------------------------------------------
    def set_stf(
        mode: str = "auto", window: str | None = None, channels: list[dict] | None = None
    ) -> dict:
        if mode == "auto":
            stf = server.handlers.compute_auto_stf(window)
            return {"stf": stf}
        if mode == "off":
            server.handlers.set_stf_enabled(False, window)
            return {"enabled": False}
        if mode == "on":
            server.handlers.set_stf_enabled(True, window)
            return {"enabled": True}
        if mode == "manual":
            if not channels:
                raise ToolError("set_stf(mode='manual') requires channels")
            server.handlers.set_stf(channels, window)
            return {"channels": channels}
        raise ToolError(f"Unknown mode: {mode!r} (auto, on, off, manual)")

    async def render_view(
        view: str | None = None, max_size: int = 1024, stretch: str = "current"
    ) -> ImageResult:
        from .render import render_png

        target = _target_view(server, view)
        if target is None:
            raise ToolError("No view to render: open an image first")
        return await render_png(server, target, max_size=max_size, stretch=stretch)

    # --- previews -----------------------------------------------------------
    def previews(
        action: str,
        window: str | None = None,
        preview_id: str = "",
        rect: list[int] | None = None,
        new_id: str = "",
    ) -> dict:
        if action == "new":
            if rect is None or len(rect) != 4:
                raise ToolError("previews(action='new') requires rect=[x0, y0, x1, y1]")
            created = server.handlers.new_preview(*(int(v) for v in rect), preview_id, window)
            return {"preview": created}
        if action == "modify":
            if rect is None or len(rect) != 4:
                raise ToolError("previews(action='modify') requires rect=[x0, y0, x1, y1]")
            return {"preview": server.handlers.modify_preview(
                preview_id, *(int(v) for v in rect), window)}
        if action == "delete":
            server.handlers.delete_preview(preview_id, window)
            return {"deleted": preview_id}
        if action == "rename":
            return {"preview": server.handlers.rename_preview(preview_id, new_id, window)}
        if action == "store":
            return {"preview": server.handlers.store_preview(preview_id, window)}
        raise ToolError(f"Unknown action: {action!r} (new, modify, delete, rename, store)")

    # --- console ------------------------------------------------------------
    async def execute_python(code: str) -> dict:
        loop = asyncio.get_running_loop()
        console = server.console
        with _StreamCollector(server) as streams:
            result = await loop.run_in_executor(console.executor, console.execute, code)
        return {
            **result,
            "stdout": streams.text("stdout"),
            "stderr": streams.text("stderr"),
        }

    return [
        Tool(
            name="get_state",
            description=(
                "Snapshot of the Retina session: open image windows, their views and "
                "previews, per-view processing history, active view, current project and "
                "running jobs. Call this first, and again after anything that may have "
                "changed the session. Returns no pixels — use render_view to see an image."
            ),
            input_schema=_schema(),
            handler=get_state,
        ),
        Tool(
            name="render_view",
            description=(
                "Render a view as a PNG image so you can actually look at it. Astronomical "
                "images are linear and appear black without a screen stretch: stretch="
                "'auto' computes one for this render (best for raw/linear data), 'current' "
                "uses the view's own screen transfer function, 'none' shows raw values. "
                "This is display-only and never modifies pixels."
            ),
            input_schema=_schema(
                {
                    "view": _str("View id; defaults to the active view."),
                    "max_size": _int("Longest edge in pixels (default 1024).",
                                     minimum=64, maximum=2048),
                    "stretch": _str("auto | current | none", ("auto", "current", "none")),
                }
            ),
            handler=render_view,
        ),
        Tool(
            name="open_images",
            description=(
                "Open image files (FITS, XISF, TIFF, PNG, JPEG, camera RAW) as new windows. "
                "Paths must be absolute."
            ),
            input_schema=_schema(
                {"paths": {"type": "array", "items": {"type": "string"},
                           "description": "Absolute paths to open."}},
                ("paths",),
            ),
            handler=open_images,
            mutating=True,
        ),
        Tool(
            name="save_image",
            description=(
                "Write a window's main view to disk. The format follows the extension "
                "(.fits, .xisf, .tif, .png, .jpg)."
            ),
            input_schema=_schema(
                {
                    "path": _str("Absolute destination path."),
                    "window": _str("Window id; defaults to the active window."),
                },
                ("path",),
            ),
            handler=save_image,
            mutating=True,
        ),
        Tool(
            name="project",
            description=(
                "Open, save or close a .retina project — a single file holding the whole "
                "session: windows, previews, masks, screen stretches and every history "
                "state, so undo still works after reopening."
            ),
            input_schema=_schema(
                {
                    "action": _str("open | save | close", ("open", "save", "close")),
                    "path": _str("Absolute .retina path (required to open)."),
                },
                ("action",),
            ),
            handler=project,
            mutating=True,
        ),
        Tool(
            name="list_processes",
            description=(
                "List the available image-processing operations, one line each: id, "
                "category and a one-sentence summary. Filter by category to keep it short. "
                "Use describe_process to get the parameters of one before applying it."
            ),
            input_schema=_schema(
                {"category": _str("Restrict to one category, e.g. 'IntensityTransformations'.")}
            ),
            handler=list_processes,
        ),
        Tool(
            name="describe_process",
            description=(
                "Full parameter schema and reference documentation for one process: every "
                "parameter with its type, default and range. Read this before apply_process "
                "unless you already know the parameters."
            ),
            input_schema=_schema(
                {"process_id": _str("Process id, e.g. 'HistogramTransformation'.")},
                ("process_id",),
            ),
            handler=describe_process,
        ),
        Tool(
            name="apply_process",
            description=(
                "Apply a process to a view (or run a global process, e.g. Integration, "
                "which creates a new window). The operation is pushed onto the view's "
                "history, so it can always be undone. Measurement processes such as "
                "DynamicPSF or Statistics return their measurements in 'result'."
            ),
            input_schema=_schema(
                {
                    "process_id": _str("Process id, e.g. 'GaussianConvolution'."),
                    "params": {"type": "object", "description": "Parameter values by id.",
                               "additionalProperties": True},
                    "view": _str("Target view id; defaults to the active view."),
                    "wait": _bool("Wait for completion (default true). Pass false for long "
                                  "operations and poll with the jobs tool.", True),
                },
                ("process_id",),
            ),
            handler=apply_process,
            mutating=True,
        ),
        Tool(
            name="apply_recipe",
            description=(
                "Apply an ordered list of processes to one view as a single history step — "
                "the reproducible 'recipe' primitive. Each entry is "
                "{process_id, values{}}. Order matters: stretch then denoise is not denoise "
                "then stretch."
            ),
            input_schema=_schema(
                {
                    "processes": {
                        "type": "array",
                        "description": "Ordered steps: {process_id, values{}}.",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                    "view": _str("Target view id; defaults to the active view."),
                    "wait": _bool("Wait for completion (default true).", True),
                },
                ("processes",),
            ),
            handler=apply_recipe,
            mutating=True,
        ),
        Tool(
            name="history",
            description=(
                "Undo, redo, or jump to any state in a view's processing history. Every "
                "processing step is reversible this way — including yours."
            ),
            input_schema=_schema(
                {
                    "action": _str("undo | redo | goto", ("undo", "redo", "goto")),
                    "view": _str("View id; defaults to the active view."),
                    "index": _int("History index for goto (0 is the original image)."),
                },
                ("action",),
            ),
            handler=history,
            mutating=True,
        ),
        Tool(
            name="get_stats",
            description=(
                "Robust statistics for a view: per-channel median, MADN, min, max and a "
                "histogram — computed on float32, the numbers the application itself uses. "
                "Pass x and y instead to probe a single point (readout)."
            ),
            input_schema=_schema(
                {
                    "view": _str("View id; defaults to the active view."),
                    "bins": _int("Histogram bins (default 64).", minimum=2, maximum=1024),
                    "x": {"type": "number", "description": "Probe x, in image pixels."},
                    "y": {"type": "number", "description": "Probe y, in image pixels."},
                    "n": _int("Probe box size in pixels (odd, default from settings)."),
                }
            ),
            handler=get_stats,
        ),
        Tool(
            name="set_stf",
            description=(
                "Control the screen transfer function — the non-destructive display stretch. "
                "'auto' derives it from robust statistics (this is what makes a linear "
                "astronomical image visible); it never alters pixel data."
            ),
            input_schema=_schema(
                {
                    "mode": _str("auto | on | off | manual", ("auto", "on", "off", "manual")),
                    "window": _str("Window id; defaults to the active window."),
                    "channels": {
                        "type": "array",
                        "description": "For mode='manual': {shadows, midtones, highlights}.",
                        "items": {"type": "object", "additionalProperties": True},
                    },
                }
            ),
            handler=set_stf,
            mutating=True,
        ),
        Tool(
            name="previews",
            description=(
                "Manage previews — named rectangular sub-regions that behave exactly like "
                "full views, so a process can be tried on one before committing to the "
                "whole image."
            ),
            input_schema=_schema(
                {
                    "action": _str("new | modify | delete | rename | store",
                                   ("new", "modify", "delete", "rename", "store")),
                    "window": _str("Window id; defaults to the active window."),
                    "preview_id": _str("Preview id (target for all actions but 'new')."),
                    "rect": {"type": "array", "items": {"type": "integer"},
                             "description": "[x0, y0, x1, y1] in image pixels."},
                    "new_id": _str("New name, for action='rename'."),
                },
                ("action",),
            ),
            handler=previews,
            mutating=True,
        ),
        Tool(
            name="jobs",
            description=(
                "Inspect or steer background work: list running jobs, get one job's state "
                "and progress, wait for it, or cancel it (cancellation is cooperative and "
                "takes effect at the next checkpoint)."
            ),
            input_schema=_schema(
                {
                    "action": _str("list | get | wait | cancel", ("list", "get", "wait", "cancel")),
                    "job": _str("Job id, for get/wait/cancel."),
                }
            ),
            handler=jobs,
        ),
        Tool(
            name="execute_python",
            description=(
                "Run Python in Retina's embedded IPython console. The namespace holds 'app' "
                "and 'retina' — the same live objects the user's own console sees, so state "
                "persists between calls and anything the API can do is reachable here. Use "
                "it for what the typed tools do not cover; prefer them when they fit. This "
                "has the same reach as the user's console, including the filesystem."
            ),
            input_schema=_schema({"code": _str("Python source to execute.")}, ("code",)),
            handler=execute_python,
            mutating=True,
        ),
    ]


def _job_outcome(server: ServerApp, job: dict, view: str | None) -> dict:
    outcome: dict[str, Any] = {
        "state": job["state"],
        "process": job["process_id"],
    }
    if job["message"]:
        outcome["message"] = job["message"]
    if job["result"] is not None:
        outcome["result"] = job["result"]
    digest = view_digest(server, view)
    if digest is not None:
        outcome["view"] = digest
    # A global process creates a window: without this, the agent would not know where the
    # result of its integration landed.
    if view is None or job["view"] is None:
        outcome["state_after"] = compact_state(server)
    return outcome


def _catalog(registry: ToolRegistry) -> list[dict]:
    """Summary catalogue, built once: the process registry does not move."""
    if registry._catalog is not None:
        return registry._catalog

    from ...documentation import doc_meta, has_doc
    from ...process.registry import all_processes

    entries = []
    for pid, cls in sorted(all_processes().items()):
        entry = {"process_id": pid, "category": getattr(cls, "category", "General")}
        if getattr(cls, "is_global", False):
            entry["is_global"] = True
        if has_doc(pid):
            brief = doc_meta(pid, "en").get("brief", "")
            if brief:
                entry["summary"] = brief
        entries.append(entry)
    registry._catalog = entries
    return entries
