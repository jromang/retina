"""``retina.parameters`` — what a script exports in order to become replayable.

The central piece of one idea: **a script execution can be a processing object**. A script that
calls ``parameters.set(...)`` produces, at the end of its execution, an instance of the
:class:`~retina.processes.script.Script` process — which enters the view's history, can be
undone, is stored as a library icon, and is replayed inside a recipe.

It is the bridge between pillar #1 (everything is scriptable) and pillar #4 (everything is
replayable). Without it, a script was a dead end: it modified views without anyone ever being
able to say *with which settings*, nor to replay it other than by relaunching it by hand.

# The rule that avoids the duplicate

An instance is created **only if** the script exported at least one parameter. A script that
merely chains ``app.apply(...)`` calls already leaves its normal history, step by step; adding
a "Script" entry on top would describe it twice. Exporting a parameter is therefore how a
script declares: "my unit of work is me, not my steps".

# Thread-local context

Same mechanism as :mod:`retina.process.context`: one thread = one execution = one context. Two
scripts launched in parallel from two clients cannot mix their parameters.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

_tls = threading.local()


@dataclass
class ParameterContext:
    """Parameters exported by the script in progress, and its target."""

    values: dict[str, Any] = field(default_factory=dict)
    target_view: Any = None
    #: True when **replaying** an instance: it must not register itself again.
    replaying: bool = False


def current() -> ParameterContext | None:
    return getattr(_tls, "context", None)


def set_context(context: ParameterContext | None) -> None:
    """Install (or remove) the current thread's context."""
    _tls.context = context


class _Parameters:
    """The facade exposed as ``retina.parameters``.

    Outside a script execution, writes are **silently ignored** and reads return the default:
    calling a function from a script in the console must not raise.
    """

    # --- writing --------------------------------------------------------------
    def set(self, identifier: str, value: Any) -> None:
        """Declare a parameter. This gesture is what makes the script replayable."""
        context = current()
        if context is not None:
            context.values[str(identifier)] = value

    def remove(self, identifier: str) -> None:
        context = current()
        if context is not None:
            context.values.pop(str(identifier), None)

    def clear(self) -> None:
        context = current()
        if context is not None:
            context.values.clear()

    # --- reading --------------------------------------------------------------
    def has(self, identifier: str) -> bool:
        context = current()
        return context is not None and str(identifier) in context.values

    def get(self, identifier: str, default: Any = None) -> Any:
        context = current()
        return default if context is None else context.values.get(str(identifier), default)

    def get_bool(self, identifier: str, default: bool = False) -> bool:
        value = self.get(identifier, default)
        # A value read back from XML arrives as text: `bool("false")` is True, and the
        # parameter unchecked on the last run would come back checked.
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def get_int(self, identifier: str, default: int = 0) -> int:
        try:
            return int(self.get(identifier, default))
        except (TypeError, ValueError):
            return default

    def get_real(self, identifier: str, default: float = 0.0) -> float:
        try:
            return float(self.get(identifier, default))
        except (TypeError, ValueError):
            return default

    def get_str(self, identifier: str, default: str = "") -> str:
        value = self.get(identifier, default)
        return default if value is None else str(value)

    def values(self) -> dict[str, Any]:
        """A copy of everything exported — what the ``Script`` instance will memorize."""
        context = current()
        return {} if context is None else dict(context.values)

    # --- target ---------------------------------------------------------------
    @property
    def target_view(self):
        """The view the script is executed on, or ``None`` in a global context."""
        context = current()
        return None if context is None else context.target_view

    @property
    def is_view_target(self) -> bool:
        return self.target_view is not None

    @property
    def is_global_target(self) -> bool:
        return current() is not None and self.target_view is None

    def __repr__(self) -> str:  # pragma: no cover — console convenience
        context = current()
        if context is None:
            return "<parameters: outside a script execution>"
        return f"<parameters {context.values!r} target={context.target_view!r}>"


#: Singleton — a facade object; the state lives in the thread-local context.
parameters = _Parameters()
