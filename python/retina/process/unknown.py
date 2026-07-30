"""``UnknownProcess`` — what stands in for a process we no longer know how to build.

The case is ordinary as soon as extensions exist: a project saved with a plugin installed,
reopened on a machine that lacks it. Without a placeholder, ``Process.from_dict`` raises a
``KeyError`` and **opening the entire project fails** — over one history step the user may not
even have intended to replay.

The standard answer is a placeholder instance that replaces processes that are uninstalled or
unknown when loading projects and processing histories.

Two properties are what make this object worthwhile:

* it **keeps the original dict intact** — re-saving the project on the machine that lacks the
  plugin loses nothing, and reopening it where the plugin exists recovers the real instance. A
  placeholder that threw the values away would turn a temporary absence into a permanent loss;
* it **refuses to execute**, with a message naming the missing process. A silent placeholder
  would do worse than the original error: the recipe would run while skipping a step.

It is **not** entered in the registry: it is not a process one chooses, it is what one finds
in place of another.
"""

from __future__ import annotations

from typing import Any


class UnknownProcess:
    """Instance of a process whose ``process_id`` is not installed.

    Duck-typed well enough to travel through the history, serialization and display: what the
    rest of the code asks of an instance is ``process_id``, ``to_dict()``, ``values()`` and a
    ``repr``.
    """

    #: False: an unknown process can neither receive a mask nor be replayed globally.
    is_maskable = False
    is_global = False
    creates_window = False
    supports_realtime = False
    category = "Unknown"

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = dict(data)
        self.process_id = str(data.get("process_id", "?"))

    def values(self) -> dict[str, Any]:
        return dict(self._data.get("values", {}))

    def to_dict(self) -> dict[str, Any]:
        """The original dict, unchanged — the whole point of the placeholder."""
        return dict(self._data)

    def cache_values(self) -> dict[str, Any]:
        return self.values()

    # --- execution: refused, but said out loud --------------------------------
    def _refusal(self) -> RuntimeError:
        return RuntimeError(
            f'Process "{self.process_id}" unavailable: the module that provides it is not '
            "installed in this copy of Retina. The step has been kept as is and will be "
            "re-saved intact, but it cannot be replayed here."
        )

    def execute_on(self, view) -> bool:
        raise self._refusal()

    def execute_on_image(self, image):
        raise self._refusal()

    def execute_global(self, app) -> bool:
        raise self._refusal()

    def realtime_capable(self) -> bool:
        return False

    def to_python_source(self, target: str = "view") -> str:
        """A comment, not code: returning an executable call would lie about what we have."""
        args = ", ".join(f"{k}={v!r}" for k, v in self.values().items())
        return f"# process unavailable: {self.process_id}({args})"

    def _describe(self) -> str:
        return f"{self.process_id} (unavailable)"

    def __repr__(self) -> str:
        return f"UnknownProcess({self.process_id!r})"


def process_from_dict(data: dict[str, Any]) -> Any:
    """``Process.from_dict``, but degrading to :class:`UnknownProcess` instead of raising.

    The single entry point of project loading. ``TypeError`` is caught on the same footing as
    ``KeyError``: a process installed in an older version may have lost a parameter since, and
    an ``__init__`` that refuses an unknown keyword must not carry the opening away either.
    """
    from .base import Process

    try:
        return Process.from_dict(data)
    except (KeyError, TypeError):
        return UnknownProcess(data)
