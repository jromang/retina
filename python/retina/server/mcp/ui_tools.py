"""MCP tools that act on the *interface*: open a script, show a documentation page.

These two tools exist for the assistant's role as a **teacher**: show rather than tell. They
do not touch the domain (an opened script is not executed, a displayed page changes nothing)
— their effect is a notification that the client turns into a Monaco tab or a documentation
page.

That is also why they stay useful to an **external** agent (Claude Code in a terminal): the
user sees what the agent is preparing for them, in their application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .tools import Tool, ToolError, _schema, _str

if TYPE_CHECKING:
    from .tools import ToolRegistry


def tools(registry: ToolRegistry) -> list[Tool]:
    server = registry.server

    def open_script(content: str, path: str | None = None, title: str = "") -> dict:
        if path:
            # Same resolution and same guards as the `fs.write_text` RPC: a relative path
            # or a nonexistent parent are errors, not silent creations. A file written
            # here is a file that `fs.*` knows how to read back.
            written = server.fs_handlers.write_text(path, content)
            server.broadcast.notify(
                "scripts.command", {"op": "open", "path": written["path"], "text": content}
            )
            return {"opened": written["path"], "size": written["size"]}
        server.broadcast.notify(
            "scripts.command", {"op": "open", "path": None, "text": content, "title": title}
        )
        return {"opened": title or "untitled"}

    def open_documentation(process_id: str) -> dict:
        from ...documentation import has_doc
        from ...process.registry import all_processes

        if process_id not in all_processes():
            raise ToolError(f"Unknown process: {process_id!r}")
        if not has_doc(process_id):
            raise ToolError(
                f"{process_id} has no documentation page — describe_process still works."
            )
        # The doc tab is driven by the visibility of the doc "panel": we go through the
        # domain (echoed), and the notification tells the viewer WHICH page to load.
        server.app.layout.show("doc")
        server.broadcast.notify("docs.command", {"op": "open", "process_id": process_id})
        return {"opened": process_id}

    return [
        Tool(
            name="open_script",
            description=(
                "Open a Python script in the user's Monaco editor, visible immediately. "
                "With 'path' the file is written to disk first (absolute path, existing "
                "parent) and the tab tracks it; without, an untitled tab opens. Use this "
                "to hand the user a script they can read, edit and run — including a new "
                "Process class file, which you then register with execute_python."
            ),
            input_schema=_schema(
                {
                    "content": _str("The Python source to show."),
                    "path": _str("Absolute path to write the file to (optional)."),
                    "title": _str("Tab title for an untitled script (optional)."),
                },
                ("content",),
            ),
            handler=open_script,
            mutating=True,
        ),
        Tool(
            name="open_documentation",
            description=(
                "Open a process's documentation page in the user's interface. Use it "
                "while explaining a process, so the user reads the same page you cite."
            ),
            input_schema=_schema(
                {"process_id": _str("Process id, e.g. 'HistogramTransformation'.")},
                ("process_id",),
            ),
            handler=open_documentation,
            mutating=True,
        ),
    ]


__all__ = ["tools"]
