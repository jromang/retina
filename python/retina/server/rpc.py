"""JSON-RPC 2.0 dispatcher.

# Explicit registry, never a ``getattr``

It would be tempting to route ``app.set_zoom`` to ``getattr(app, "set_zoom")``: one line
instead of a registry. That would expose the *entire* surface of the application object to
whoever reaches the WebSocket — including private attributes and everything that will be
added tomorrow without a second thought. Every method is therefore declared, with its
argument conversion.

# ``mutating``

After a call that modifies state, the dispatcher marks the snapshot as stale. This is what
replaces the events the domain does not emit: rather than hoping each method reports its
effects, we redeclare the complete state, once per burst.

# ``current_connection``

The viewport is rendered optimistically on the client side: it moves its camera locally, then
tells the server. When the ``viewport.changed`` notification comes back, the author of the
gesture must ignore it (it is already up to date) but the *other* clients — and above all the
console — must apply it. Hence this ``ContextVar``, set for the duration of a call: it is a
``contextvars`` and not an attribute, so as to survive the task's ``await``s correctly.
"""

from __future__ import annotations

import contextvars
import inspect
import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("retina.server")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
#: application error (the domain raised) — "implementation-defined" range of the standard
DOMAIN_ERROR = -32000

#: Id of the connection at the origin of the current call (``None`` = console/script).
current_connection: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "retina_rpc_connection", default=None
)


class RpcError(Exception):
    """Error meant to be returned as is to the client."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass(frozen=True)
class Method:
    handler: Callable[..., Any]
    mutating: bool
    doc: str


class Dispatcher:
    """Table of exposed methods + execution of a request."""

    def __init__(self, on_mutation: Callable[[], None] | None = None) -> None:
        self._methods: dict[str, Method] = {}
        self._on_mutation = on_mutation

    def register(self, name: str, handler: Callable[..., Any], *, mutating: bool = False) -> None:
        if name in self._methods:
            raise ValueError(f"method already registered: {name!r}")
        doc = (inspect.getdoc(handler) or "").strip().split("\n", 1)[0]
        self._methods[name] = Method(handler, mutating, doc)

    def register_all(self, handlers: object, table: dict[str, bool]) -> None:
        """Registers ``{RPC name: mutating}`` by resolving the methods on ``handlers``.

        The RPC name ``app.set_zoom`` maps to the object's ``set_zoom`` method.
        """
        for name, mutating in table.items():
            attribute = name.split(".", 1)[1].replace(".", "_")
            handler = getattr(handlers, attribute, None)
            if handler is None:
                raise AttributeError(f"{type(handlers).__name__} does not implement {attribute!r}")
            self.register(name, handler, mutating=mutating)

    def methods(self) -> dict[str, str]:
        """Name → first line of the docstring (introspection from the frontend)."""
        return {name: method.doc for name, method in sorted(self._methods.items())}

    async def dispatch(self, request: Any, connection: str | None = None) -> dict | None:
        """Runs an already deserialized JSON-RPC request. ``None`` = silent notification."""
        if not isinstance(request, dict):
            return _error(None, INVALID_REQUEST, "JSON-RPC request expected (object)")

        req_id = request.get("id")
        name = request.get("method")
        if not isinstance(name, str):
            return _error(req_id, INVALID_REQUEST, "'method' field missing or invalid")

        method = self._methods.get(name)
        if method is None:
            return _error(req_id, METHOD_NOT_FOUND, f"unknown method: {name!r}")

        params = request.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(req_id, INVALID_PARAMS, "'params' must be an object (named arguments)")

        token = current_connection.set(connection)
        try:
            result = method.handler(**params)
            if inspect.isawaitable(result):
                result = await result
        except RpcError as exc:
            return _error(req_id, exc.code, str(exc), exc.data)
        except TypeError as exc:
            # incompatible signature: this is a call error, not a server failure
            if "argument" in str(exc):
                return _error(req_id, INVALID_PARAMS, f"{name}: {exc}")
            return _domain_error(req_id, name, exc)
        except (KeyError, ValueError, RuntimeError) as exc:
            return _domain_error(req_id, name, exc)
        except Exception as exc:
            log.exception("internal error in %s", name)
            return _error(
                req_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}",
                {"traceback": traceback.format_exc()},
            )
        finally:
            current_connection.reset(token)

        if method.mutating and self._on_mutation is not None:
            self._on_mutation()

        if req_id is None:
            return None  # notification: the standard forbids answering
        return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


def _domain_error(req_id: Any, name: str, exc: Exception) -> dict:
    """The domain refused the call — this is a normal response, not a server incident."""
    log.debug("%s failed: %s", name, exc)
    return _error(req_id, DOMAIN_ERROR, f"{type(exc).__name__}: {exc}")
