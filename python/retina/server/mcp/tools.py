"""MCP tool registry — the surface an agent sees.

# Discipline

Like the ``handlers_*.py`` families, **no tool contains business logic**: each one converts
its arguments and delegates to an existing handler or to ``app.*``. A tool that did otherwise
would create a capability reserved to the agent — the same architecture fault that
console/GUI parity forbids the web shell.

# Three choices that govern the file

**The catalogue is read in two steps.** ``list_processes`` returns one line per process;
``describe_process`` returns the parameter schema and documentation of a single one. Dumping
the 122 schemas at once would cost tens of thousands of tokens per conversation, for an agent
that will use two or three of them.

**Every mutating tool returns its echo.** ``app`` publishes, for each action, the equivalent
Python code (``on_echo``); we collect it during the call and return it to the agent. It
therefore learns the API by acting, exactly like the user watching their console — and what it
returns can be copied straight into a script.

**The descriptions are in English, outside ``gettext``.** This is a machine interface, on the
same footing as the ``process_id``s and the echoes: an agent contract that changed language
according to the server's locale would give different behaviors on two machines.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..rpc import RpcError

if TYPE_CHECKING:
    from ..core import ServerApp

#: Beyond this, a script's output is truncated from the tail: an agent does not need the
#: fifty thousand lines of a preprocessing run, and its context would not survive them.
MAX_OUTPUT_CHARS = 16_000


class ToolError(Exception):
    """*Expected* failure of a tool — returned to the agent as a failed result.

    To be distinguished from an unforeseen exception, which surfaces as a server fault: here
    the agent is meant to read the message and correct its call.
    """


@dataclass(frozen=True)
class ImageResult:
    """A visual rendering, to be carried as an MCP image block rather than as JSON."""

    png: bytes
    caption: str = ""


@dataclass(frozen=True)
class ToolResult:
    """What a call returns to the transport: MCP content blocks."""

    content: list[dict]
    is_error: bool = False

    def to_dict(self) -> dict:
        return {"content": self.content, "isError": self.is_error}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[..., Any]
    #: A mutating tool has its echoes collected and attached to the result.
    mutating: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# --------------------------------------------------------------------------- #
# Schemas                                                                      #
# --------------------------------------------------------------------------- #
def _schema(properties: dict | None = None, required: tuple[str, ...] = ()) -> dict:
    return {
        "type": "object",
        "properties": properties or {},
        "required": list(required),
        "additionalProperties": False,
    }


def _str(description: str, enum: tuple[str, ...] = ()) -> dict:
    entry: dict = {"type": "string", "description": description}
    if enum:
        entry["enum"] = list(enum)
    return entry


def _int(description: str, **bounds: int) -> dict:
    return {"type": "integer", "description": description, **bounds}


def _bool(description: str, default: bool | None = None) -> dict:
    entry: dict = {"type": "boolean", "description": description}
    if default is not None:
        entry["default"] = default
    return entry


# --------------------------------------------------------------------------- #
# Capturing the echo and the console output                                    #
# --------------------------------------------------------------------------- #
class _Collector:
    """Collects the Python echoes emitted during a tool call.

    Accepted limitation: the listener lists are global to the server, so two concurrent calls
    — or a mouse gesture made while a tool is running — will mix their echoes. In practice
    MCP clients serialize their calls, and one echo too many is informative, not dangerous.
    """

    def __init__(self, server: ServerApp) -> None:
        self._server = server
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def __enter__(self) -> _Collector:
        self._server.echo_listeners.append(self._append)
        return self

    def __exit__(self, *_exc: object) -> None:
        with contextlib.suppress(ValueError):  # removed twice: of no consequence
            self._server.echo_listeners.remove(self._append)

    def _append(self, code: str) -> None:
        with self._lock:
            self._lines.append(code)

    @property
    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)


class _StreamCollector:
    """Same mechanism, for the stdout/stderr of a script run by ``execute_python``."""

    def __init__(self, server: ServerApp) -> None:
        self._server = server
        self._chunks: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def __enter__(self) -> _StreamCollector:
        self._server.stream_listeners.append(self._append)
        return self

    def __exit__(self, *_exc: object) -> None:
        with contextlib.suppress(ValueError):
            self._server.stream_listeners.remove(self._append)

    def _append(self, name: str, text: str) -> None:
        with self._lock:
            self._chunks.append((name, text))

    def text(self, name: str) -> str:
        with self._lock:
            joined = "".join(t for n, t in self._chunks if n == name)
        return _truncate(joined)


def _truncate(text: str) -> str:
    """Keeps the **tail**: that is where the error and the result are."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return f"[… {len(text) - MAX_OUTPUT_CHARS} characters truncated …]\n" + text[-MAX_OUTPUT_CHARS:]


# --------------------------------------------------------------------------- #
# Registry                                                                     #
# --------------------------------------------------------------------------- #
@dataclass
class Handles:
    """A small store of domain objects too bulky for an agent's context.

    An inventory of three hundred frames or a preprocessing plan weighs hundreds of kilobytes
    of JSON. The ``pipeline.*`` handlers route them through the client — the right choice for
    the web shell, which needs to display them, and the wrong one for an LLM, whose context
    would be saturated by data it does not have to read. We therefore keep them here and
    return only a **handle** (``inv1``, ``plan2``) with a summary.
    """

    _items: dict[str, Any] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def put(self, kind: str, value: Any) -> str:
        self._counters[kind] = self._counters.get(kind, 0) + 1
        key = f"{kind}{self._counters[kind]}"
        self._items[key] = value
        return key

    def get(self, key: str, kind: str) -> Any:
        value = self._items.get(key)
        if value is None or not key.startswith(kind):
            raise ToolError(
                f"Unknown {kind} handle: {key!r}. "
                f"Known handles: {', '.join(sorted(self._items)) or 'none'}"
            )
        return value

    def replace(self, key: str, value: Any) -> None:
        self._items[key] = value


class ToolRegistry:
    """The tools, independently of the transport that exposes them."""

    def __init__(self, server: ServerApp) -> None:
        self._server = server
        self._tools: dict[str, Tool] = {}
        #: Pipeline handles — see :mod:`~retina.server.mcp.pipeline_tools`.
        self.handles = Handles()
        self._catalog: list[dict] | None = None
        for tool in _build(self):
            if tool.name in self._tools:  # pragma: no cover — programming mistake
                raise ValueError(f"tool already registered: {tool.name!r}")
            self._tools[tool.name] = tool

    # --- access ---------------------------------------------------------------
    @property
    def server(self) -> ServerApp:
        return self._server

    def definitions(self) -> list[dict]:
        return [tool.to_dict() for tool in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    # --- call -----------------------------------------------------------------
    async def call(self, name: str, arguments: dict | None = None) -> ToolResult:
        """Runs a tool and returns its content blocks.

        A *foreseeable* failure (invalid argument, unknown view, process that refuses) becomes
        a failed result rather than a protocol error: the model reads it, understands and
        tries again. A JSON-RPC error, on the other hand, does not reach it in a usable form.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult([_text(f"Unknown tool: {name!r}")], is_error=True)

        args = dict(arguments or {})
        # The signature is checked **before** the call rather than by catching ``TypeError``
        # around it: without that, a ``TypeError`` raised *inside* the tool — a real defect —
        # would disguise itself as "wrong arguments" and send the agent off to fix a call
        # that was in fact correct. A server bug must surface as such.
        try:
            inspect.signature(tool.handler).bind(**args)
        except TypeError as exc:
            return ToolResult([_text(f"Invalid arguments for {name}: {exc}")], is_error=True)

        collector = _Collector(self._server) if tool.mutating else None
        try:
            if collector is not None:
                with collector:
                    payload = await _maybe_await(tool.handler(**args))
            else:
                payload = await _maybe_await(tool.handler(**args))
        except (ToolError, RpcError, KeyError, ValueError, OSError) as exc:
            return ToolResult([_text(f"{type(exc).__name__}: {exc}")], is_error=True)

        if isinstance(payload, ImageResult):
            return ToolResult(_image_blocks(payload))

        if collector is not None and isinstance(payload, dict):
            echo = collector.lines
            if echo:
                payload = {**payload, "echo": echo}
        return ToolResult([_text(_render(payload))])


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _image_blocks(result: ImageResult) -> list[dict]:
    import base64

    blocks: list[dict] = []
    if result.caption:
        blocks.append(_text(result.caption))
    blocks.append(
        {
            "type": "image",
            "data": base64.b64encode(result.png).decode("ascii"),
            "mimeType": "image/png",
        }
    )
    return blocks


def _render(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


# --------------------------------------------------------------------------- #
# Definitions                                                                  #
# --------------------------------------------------------------------------- #
def _build(registry: ToolRegistry) -> list[Tool]:
    from . import pipeline_tools, session_tools, ui_tools

    tools = session_tools.tools(registry)
    tools += pipeline_tools.tools(registry)
    tools += ui_tools.tools(registry)
    return tools
