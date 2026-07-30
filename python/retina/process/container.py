"""ProcessContainer — an ordered, replayable, serializable pipeline of processes.

The reproducible "recipe" primitive. It executes on a View (each step is one history entry) or
on an Image (headless). It serializes to XML (our own schema) and to Python source.

# Disabled step, per-step mask

Two capabilities that are central here: a step is disabled to try the recipe without it, and
given a mask of its own so as to apply it to only part of the image. Both are **indexed**
(``enable(i)``, ``setMask(i, maskId, invert)``): this leaves ``processes`` untouched and
serializes without trouble.

The mask is designated **by view identifier**, never by its pixels — a recipe must remain a
document. It is resolved at execution time, which raises the question of *who* knows how to
resolve: hence the ``resolve_mask`` parameter of ``execute_on``. Without it, the domain would
have to hold a reference to the application, and the container would stop being testable on
its own.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from ..i18n import translate as _t
from .base import Process
from .registry import get

RECIPE_VERSION = "1.0"


def process_to_element(process: Process, parent: ET.Element) -> ET.Element:
    """Serialize an instance into a ``<process id=…>`` element (recipe schema)."""
    pe = ET.SubElement(parent, "process", {"id": process.process_id})
    for pid, value in process.values().items():
        param = ET.SubElement(pe, "parameter", {"id": pid})
        param.text = json.dumps(value)
    return pe


def process_from_element(pe: ET.Element) -> Process:
    """Rebuild an instance from a ``<process>`` element (through the registry)."""
    process_cls = get(pe.get("id"))
    kwargs = {
        param.get("id"): json.loads(param.text or "null")
        for param in pe.findall("parameter")
    }
    return process_cls(**kwargs)


def container_to_elements(container: ProcessContainer, parent: ET.Element) -> None:
    """Write the ``<process>`` elements of a recipe, step flags included.

    Shared with :mod:`retina.library`, which has its own XML document but the same steps: the
    first version duplicated the loop over there, and a recipe stored in the library silently
    lost its disabled steps and its masks.

    Attributes are written only when they depart from the default: an ordinary recipe keeps
    the XML it had before this change, and already-saved files read back without conversion.
    """
    for index, process in enumerate(container.processes):
        pe = process_to_element(process, parent)
        if not container.enabled(index):
            pe.set("enabled", "false")
        mask_id = container.mask_id(index)
        if mask_id is not None:
            pe.set("mask", mask_id)
            if container.mask_inverted(index):
                pe.set("mask-inverted", "true")


def container_from_elements(parent: ET.Element) -> ProcessContainer:
    """Read back what :func:`container_to_elements` wrote."""
    elements = parent.findall("process")
    container = ProcessContainer([process_from_element(pe) for pe in elements])
    for index, pe in enumerate(elements):
        if pe.get("enabled") == "false":
            container.disable(index)
        mask = pe.get("mask")
        if mask:
            container.set_mask(index, mask, pe.get("mask-inverted") == "true")
    return container


class ProcessContainer:
    def __init__(self, processes: list[Process] | None = None):
        self.processes: list[Process] = list(processes or [])
        #: Parallel to ``processes`` — never exposed for direct writing, so that they cannot
        #: fall out of sync with the list of steps.
        self._enabled: list[bool] = [True] * len(self.processes)
        self._masks: list[tuple[str | None, bool]] = [(None, False)] * len(self.processes)

    def add(self, process: Process) -> ProcessContainer:
        self.processes.append(process)
        self._enabled.append(True)
        self._masks.append((None, False))
        return self

    def __len__(self) -> int:
        return len(self.processes)

    def __iter__(self):
        return iter(self.processes)

    # --- enabled / disabled steps ---------------------------------------------
    def enable(self, index: int, state: bool = True) -> None:
        """Enable (or disable) step ``index``. A disabled step is **skipped**."""
        self._check(index)
        self._enabled[index] = bool(state)

    def disable(self, index: int) -> None:
        self.enable(index, False)

    def enabled(self, index: int) -> bool:
        self._check(index)
        return self._enabled[index]

    # --- per-step mask ---------------------------------------------------------
    def set_mask(self, index: int, mask_id: str | None, invert: bool = False) -> None:
        """Mask of step ``index``, designated by **view identifier**.

        ``None`` removes the step's mask; it then falls back on the window's, if there is one.
        """
        self._check(index)
        self._masks[index] = (mask_id, bool(invert))

    def mask_id(self, index: int) -> str | None:
        self._check(index)
        return self._masks[index][0]

    def mask_inverted(self, index: int) -> bool:
        self._check(index)
        return self._masks[index][1]

    def _check(self, index: int) -> None:
        if not (0 <= index < len(self.processes)):
            raise IndexError(
                _t("Unknown step: {index} (0…{last})").format(
                    index=index, last=len(self.processes) - 1
                )
            )

    # --- execution ------------------------------------------------------------
    def execute_on(self, view, resolve_mask: Callable[[str], Any] | None = None) -> bool:
        """Apply each process in sequence on a View (one history entry per step).

        ``resolve_mask`` translates a view identifier into an
        :class:`~retina.model.image.Image`. By default the application singleton is queried —
        which is what a recipe typed in the console wants; the application passes its own.
        """
        resolver = resolve_mask or _default_mask_resolver
        for index, process in enumerate(self.processes):
            if not self._enabled[index]:
                # A message rather than silence: skipping a step is a user's choice, but
                # forgetting it and wondering why the result does not move is another one.
                print(f"* Skipping disabled step: {process.process_id}")
                continue
            mask_id, inverted = self._masks[index]
            if mask_id is None:
                process.execute_on(view)
                continue
            with _step_mask(view, _resolve(resolver, mask_id), inverted):
                process.execute_on(view)
        return True

    def execute_on_image(self, image):
        """Apply the sequence on an Image (headless). Returns a new Image.

        Per-step masks are **ignored**: they designate views, and there is no window here.
        Disabled steps, on the other hand, are still skipped.
        """
        for index, p in enumerate(self.processes):
            if self._enabled[index]:
                image = p.execute_on_image(image)
        return image

    # --- JSON serialization (wire form) ---------------------------------------
    def to_dicts(self) -> list[dict[str, Any]]:
        """Wire form of a recipe: ``Process.to_dict()`` plus the two step flags.

        Optional keys are written only when they depart from the default. An ordinary recipe
        therefore produces exactly what the previous version produced — clients that do not
        know about the flags keep on reading it.
        """
        out: list[dict[str, Any]] = []
        for index, process in enumerate(self.processes):
            step: dict[str, Any] = process.to_dict()
            if not self._enabled[index]:
                step["enabled"] = False
            mask_id, inverted = self._masks[index]
            if mask_id is not None:
                step["mask"] = mask_id
                # Same rule as for the XML and on the client side: only what departs from
                # the default is written. Without that, a round trip added
                # `mask_inverted: false` and the recipe read back no longer equaled the one
                # that had been sent.
                if inverted:
                    step["mask_inverted"] = True
            out.append(step)
        return out

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]]) -> ProcessContainer:
        container = cls([Process.from_dict(step) for step in data])
        for index, step in enumerate(data):
            if step.get("enabled") is False:
                container.disable(index)
            if step.get("mask"):
                container.set_mask(index, step["mask"], bool(step.get("mask_inverted")))
        return container

    # --- XML serialization ----------------------------------------------------
    def to_xml(self) -> str:
        root = ET.Element("recipe", {"version": RECIPE_VERSION, "generator": "retina"})
        container_to_elements(self, root)
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode")

    @classmethod
    def from_xml(cls, text: str) -> ProcessContainer:
        return container_from_elements(ET.fromstring(text))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_xml())

    @classmethod
    def load(cls, path: str) -> ProcessContainer:
        with open(path, encoding="utf-8") as fh:
            return cls.from_xml(fh.read())

    # --- Python source (echo / readable recipe) -------------------------------
    def to_python_source(self, target: str = "view") -> str:
        used = sorted({p.process_id for p in self.processes})
        lines = [f"from retina import ProcessContainer, {', '.join(used)}" if used else
                 "from retina import ProcessContainer"]
        lines.append("pc = ProcessContainer()")
        for p in self.processes:
            args = ", ".join(f"{k}={v!r}" for k, v in p.values().items())
            lines.append(f"pc.add({p.process_id}({args}))")
        for index in range(len(self.processes)):
            if not self._enabled[index]:
                lines.append(f"pc.disable({index})")
            mask_id, inverted = self._masks[index]
            if mask_id is not None:
                lines.append(f"pc.set_mask({index}, {mask_id!r}, {inverted!r})")
        lines.append(f"pc.execute_on({target})")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"ProcessContainer([{', '.join(p.process_id for p in self.processes)}])"


class _step_mask:
    """Set a step's mask on the window, then restore the original state.

    ``Process.execute_on`` reads the **window's** mask (``view.window.mask_array``): that is
    therefore where it must be set, for the duration of one step. The restoration is in a
    ``finally`` — without it, a step that fails would leave its mask in place and contaminate
    everything the user did next, by hand included.
    """

    def __init__(self, view, mask, inverted: bool) -> None:
        self._window = getattr(view, "window", None)
        self._mask = mask
        self._inverted = inverted
        self._saved: tuple[Any, bool, bool] | None = None

    def __enter__(self):
        if self._window is None or self._mask is None:
            return self
        self._saved = (
            self._window.mask,
            self._window.mask_inverted,
            self._window.mask_enabled,
        )
        self._window.set_mask(self._mask, self._inverted)
        return self

    def __exit__(self, *_exc) -> None:
        if self._saved is None:
            return
        self._window.mask, self._window.mask_inverted, self._window.mask_enabled = self._saved
        self._saved = None


def _resolve(resolver: Callable[[str], Any], mask_id: str):
    """Apply the resolver, and translate its failure into a useful message.

    The translation is **here** and not in the default resolver: the application passes its own
    (a one-line expression), and that is precisely the path the interface takes. Leaving the
    message to the resolver amounted to having it only in the least frequent case.

    A missing view **raises**. With no dialog available to us here, applying unmasked in
    silence would be the worst choice — the step would touch the whole image when it had been
    restricted on purpose.
    """
    try:
        return resolver(mask_id)
    except (KeyError, ValueError, LookupError) as exc:
        raise ValueError(
            _t(
                "Mask not found: the recipe refers to view {mask_id!r}, "
                "which is not open ({error})."
            ).format(mask_id=mask_id, error=exc)
        ) from None


def _default_mask_resolver(mask_id: str):
    """Resolve a view identifier into an image, through the application singleton.

    Lazy import: the container stays importable — and testable — without an application, which
    the ``resolve_mask`` parameter of ``execute_on`` is there to exploit.
    """
    from ..app import app

    return app.view(mask_id).image
