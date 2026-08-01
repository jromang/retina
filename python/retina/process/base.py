"""Process / Parameter — the processing meta-model.

A ``Process`` carries an ordered **schema** of typed :class:`Parameter` objects (the stable id
is the serialization key). An *instance* of a subclass is a configured ``ProcessInstance`` —
the draggable "process icon". Entry points: :meth:`execute_on` (a View),
:meth:`execute_on_image` (an Image, headless). Serializable as Python source
(:meth:`to_python_source`) for the GUI echo and for recipes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..i18n import translate as _t


@dataclass(frozen=True)
class Parameter:
    """Descriptor of a process parameter (one column of the parameter table)."""

    id: str
    #: 'real' | 'int' | 'bool' | 'enum' | 'str' | 'view' | 'path' | 'dir' | 'pathlist' |
    #: 'floatlist' | 'intlist' | 'text' | 'points'.
    #:
    #: ``view`` **is** a string as far as the domain is concerned — it coerces, serializes and
    #: replays exactly like ``str``, and a headless script assigns a plain identifier. What it
    #: adds is a statement of *what the string designates*, which is what lets the generated
    #: form offer the open views instead of a blank box. Combining SHO used to mean typing
    #: three view identifiers from memory, with a typo silently falling back to the current
    #: image.
    type: str
    default: Any
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] | None = None
    label: str = ""
    tooltip: str = ""
    #: conditional visibility, ``(controller_id, allowed_values)``: the parameter is shown in
    #: the auto-generated form only if the parameter ``controller_id`` holds one of the listed
    #: values. ``None`` = always visible. Pure UI convenience — the value stays in the instance
    #: and travels at execution time, a hidden field simply keeping its default.
    visible_when: tuple[str, tuple[Any, ...]] | None = None

    def coerce(self, value: Any) -> Any:
        if self.type == "real":
            return float(value)
        if self.type == "int":
            return int(value)
        if self.type == "bool":
            return bool(value)
        if isinstance(value, list):  # avoids sharing a mutable default across instances
            return list(value)
        return value


class Process:
    """Base class of a process. A configured instance IS the ``ProcessInstance``."""

    process_id: str = "Process"
    category: str = "General"
    parameters: list[Parameter] = []
    # "global" process: reads several frames and produces one or more new windows instead of
    # transforming the active view.
    is_global: bool = False
    # honors the window mask (blend). False for operations that change the geometry.
    is_maskable: bool = True
    # generator: produces a NEW window (a mask, an extracted channel…) instead of transforming
    # the active view. Handled by app.apply / app.run.
    creates_window: bool = False
    # eligible for the real-time preview (execute_preview on a decimated image). Processes
    # whose cost is pathological even when reduced set False. Do not read it directly:
    # `realtime_capable()` adds the structural exclusions (global, generator).
    supports_realtime: bool = True

    def __init__(self, **kwargs: Any):
        known = {p.id for p in self.parameters}
        unknown = set(kwargs) - known
        if unknown:
            raise TypeError(
                _t("{process_id}: unknown parameters {names}").format(
                    process_id=self.process_id, names=sorted(unknown)
                )
            )
        for p in self.parameters:
            setattr(self, p.id, p.coerce(kwargs.get(p.id, p.default)))

    # --- to be implemented by subclasses --------------------------------------
    def _apply(self, data: np.ndarray) -> np.ndarray:
        """Apply the operator to an ``(H, W, C)`` float32 array → a new array."""
        raise NotImplementedError

    # --- progress / cooperative cancellation ----------------------------------
    def _progress(self, fraction: float | None, message: str = "") -> None:
        """Report progress (no-op without an installed monitor). ``None`` = indeterminate."""
        from . import context

        monitor = context.get_monitor()
        if monitor is not None:
            monitor.report(fraction, message or self.process_id)

    def _checkpoint(self) -> None:
        """Cancellation point: call it inside long loops (no-op without a monitor)."""
        from . import context

        monitor = context.get_monitor()
        if monitor is not None:
            monitor.checkpoint()

    # --- execution ------------------------------------------------------------
    def execute_on_image(self, image):
        """Execute on an Image (headless, no history). Returns a new Image."""
        return image.with_data(self._apply(image.data))

    @classmethod
    def realtime_capable(cls) -> bool:
        """Eligible for the real-time preview, structural exclusions included.

        A global process, or one that generates a window, has no preview *by construction*:
        it does not transform the current view. Deriving it here rather than setting
        ``supports_realtime = False`` on each one keeps a future global process from
        forgetting to — the omission would show up as a preview button that raises in use.
        """
        return bool(cls.supports_realtime) and not cls.is_global and not cls.creates_window

    @classmethod
    def parameter_choices(cls, param_id: str) -> tuple[str, ...] | None:
        """Enumeration choices computed on the fly, or ``None`` to stick to the static ones.

        The parameter table is frozen at class definition time, but some choices are known
        only at runtime: the list of available AI models changes with what is installed and
        downloaded. The server consults this hook on **every** projection of the schema
        (``process.list``), so a model that appeared in the meantime shows up in the drop-down
        without a restart. The domain stays in charge of the answer; the server merely relays
        it.
        """
        return None

    def execute_preview(self, image, max_size: int = 1024):
        """Headless "real-time" preview: applies to a **decimated** version of the image
        (never enlarged — that is where the speed comes from). Integer decimation by stride:
        no costly resample.

        Documented limitation: parameters expressed in pixels (sigma…) render differently at
        reduced scale — the usual trade-off.
        """
        if not self.realtime_capable():
            raise RuntimeError(
                _t("{process_id}: no real-time preview").format(process_id=self.process_id)
            )
        data = image.data
        k = max(1, (max(data.shape[0], data.shape[1]) + max_size - 1) // max_size)
        if k > 1:
            data = np.ascontiguousarray(data[::k, ::k, :])
        return image.with_data(self._apply(data))

    def execute_on(self, view) -> bool:
        """Execute on a View: history bracket + application.

        If the window has an active mask and the process preserves the geometry, the result is
        blended: ``out = original·(1−m) + processed·m``. A cancellation
        (:class:`~retina.process.progress.ProcessCancelled`) discards the bracket: the view is
        not modified and the exception propagates to the worker.
        """
        from .progress import ProcessCancelled

        view.begin_process(self._describe(), process=self)
        original = view.image.data
        try:
            processed = self._apply(original)
        except ProcessCancelled:
            view.abort_process()
            raise
        processed = self.blend_mask(view, original, processed, note=True)
        view.set_image(view.image.with_data(processed))
        view.end_process()
        return True

    def blend_mask(self, view, original, processed, *, note: bool = False):
        """Blend the result through the window mask: ``orig·(1−m) + processed·m``.

        Extracted from :meth:`execute_on` so that **replay** (``View.replay``) applies exactly
        the same blend: two implementations of this mix would eventually have differed, and
        the discrepancy would only have shown at the edges of the mask.

        ``note=True`` records along the way, in the history entry in progress, *which* mask
        served — what replay will read back later instead of taking the current one.
        """
        if not (self.is_maskable and processed.shape == original.shape
                and view.window is not None):
            return processed
        rect = view.rect if view.is_preview else None
        m = view.window.mask_array(original.shape, rect=rect)
        if note:
            identifier = getattr(view.window, "mask_source_id", None) if m is not None else None
            view.note_mask(identifier, bool(getattr(view.window, "mask_inverted", False)))
        if m is None:
            return processed
        return (original * (1.0 - m) + processed * m).astype(processed.dtype)

    def execute_global(self, app) -> bool:
        """Global (multi-frame) process: reads its inputs and creates windows through ``app``.

        Default: not global. Subclasses with ``is_global = True`` implement it.
        """
        raise NotImplementedError(
            _t("{process_id} is not a global process").format(process_id=self.process_id)
        )

    # --- serialization / echo -------------------------------------------------
    def values(self) -> dict[str, Any]:
        return {p.id: getattr(self, p.id) for p in self.parameters}

    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible representation (the basis of drag & drop and of the library)."""
        return {"process_id": self.process_id, "values": self.values()}

    def cache_values(self) -> dict[str, Any]:
        """The parameters the **file** produced by this process depends on.

        All of them by default: changing a parameter changes the output, and so invalidates
        the pipeline's execution cache. A process may exclude those that bear only on a
        post-processing step fast enough to be redone on every run — the case of
        :class:`~retina.processes.subframe.SubframeSelector`, whose expressions evaluate in a
        millisecond where the measurements cost one star detection per frame. Excluding them
        here is what makes it possible to reject six frames without paying again for the
        measurement of the other hundred.
        """
        return self.values()

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Process:
        from .registry import get

        return get(data["process_id"])(**data.get("values", {}))

    def _describe(self) -> str:
        return self.process_id

    def to_python_source(self, target: str = "view") -> str:
        """The equivalent executable Python code (for the GUI echo and for recipes)."""
        args = ", ".join(f"{k}={v!r}" for k, v in self.values().items())
        method = "execute_global" if self.is_global else "execute_on"
        return f"{self.process_id}({args}).{method}({target})"

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.values().items())
        return f"{self.process_id}({args})"

    # --- documentation --------------------------------------------------------
    @classmethod
    def doc(cls, lang: str = "fr") -> str:
        """Markdown documentation of the process (body, without the frontmatter).

        Works on an instance too. Raises ``KeyError`` if no documentation exists.
        """
        from .. import documentation as _doc  # lazy import (avoids the cycle)

        return _doc.doc_markdown(cls.process_id, lang)

    @classmethod
    def help(cls, lang: str = "fr") -> None:
        """Print the process documentation to the console."""
        try:
            print(cls.doc(lang))
        except KeyError:
            print(f"{cls.process_id}: no documentation yet.")
