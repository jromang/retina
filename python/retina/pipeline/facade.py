"""Application facade: ``app.pipeline`` — the same API, but one that echoes itself.

The console calls ``retina.pipeline.scan(...)`` directly: it is already Python, there is
nothing to echo. The GUI, for its part, goes through ``app.pipeline``: every gesture of the
wizard then emits into the console the Python that would have produced it, executable and
copyable. Concatenated, those echoes form the script of the pre-processing run just done
with the mouse.

It is the same arrangement as :class:`retina.library.Library`, into which the
``Application`` injects its ``_echo``: the logic stays in the domain, the facade only
announces.
"""

from __future__ import annotations

from collections.abc import Callable

from .editing import hooks as _hooks
from .editing import set_hooks as _set_hooks
from .editing import set_step_params as _set_step_params
from .groups import Survey
from .groups import survey as _survey
from .plan import Plan
from .plan import plan as _plan
from .presets import Preset, describe_presets
from .runner import RunReport
from .runner import run as _run
from .scan import Inventory
from .scan import exclude as _exclude
from .scan import reclassify as _reclassify
from .scan import scan as _scan
from .selection import criteria as _criteria
from .selection import measures as _measures
from .selection import rejects as _rejects
from .selection import set_criteria as _set_criteria
from .selection import set_rejects as _set_rejects
from .selection import summary as _summary


def _format_paths(paths) -> str:
    """Paths as an executable Python literal — a lone string stays a string."""
    if isinstance(paths, str):
        return repr(paths)
    return "[" + ", ".join(repr(str(p)) for p in paths) + "]"


class PipelineFacade:
    """``app.pipeline`` — delegates to the domain and echoes the equivalent Python."""

    def __init__(self, echo: Callable[[str], None] | None = None) -> None:
        self._echo = echo or (lambda code: None)

    def scan(self, path: str, *, recursive: bool = True) -> Inventory:
        inventory = _scan(path, recursive=recursive)
        suffix = "" if recursive else ", recursive=False"
        self._echo(f"inventory = retina.pipeline.scan({path!r}{suffix})")
        return inventory

    def survey(self, inventory: Inventory, preset: str | Preset | dict | None = None) -> Survey:
        """Grouping and matching — read-only, hence nothing to echo.

        The preset is accepted for its **tolerances**: without it, the wizard's table would
        group differently from the plan it announces, and the discrepancy would show only at
        run time.
        """
        from .presets import resolve

        tolerances = resolve(preset).tolerances() if preset is not None else {}
        return _survey(inventory, **tolerances)

    def reclassify(self, inventory: Inventory, paths, kind: str) -> Inventory:
        result = _reclassify(inventory, paths, kind)
        self._echo("inventory = retina.pipeline.reclassify"
                   f"(inventory, {_format_paths(paths)}, {kind!r})")
        return result

    def exclude(self, inventory: Inventory, paths, excluded: bool = True) -> Inventory:
        result = _exclude(inventory, paths, excluded)
        suffix = "" if excluded else ", excluded=False"
        self._echo(f"inventory = retina.pipeline.exclude"
                   f"(inventory, {_format_paths(paths)}{suffix})")
        return result

    def plan(self, inventory: Inventory, preset: str | Preset | dict | None = "auto",
             *, output_dir: str | None = None, groups=None) -> Plan:
        result = _plan(inventory, preset, output_dir=output_dir, groups=groups)
        name = preset if isinstance(preset, str) else result.preset.name
        suffix = f", output_dir={output_dir!r}" if output_dir else ""
        # A hand-corrected grouping must appear in the echo: without this `groups=`, the
        # replayed script would redo the automatic grouping — hence not the same plan.
        suffix += ", groups=batches" if groups is not None else ""
        self._echo(f"plan = retina.pipeline.plan(inventory, preset={name!r}{suffix})")
        return result

    def run(self, plan: Plan, on_progress=None, *, force: bool = False) -> RunReport:
        self._echo(f"retina.pipeline.run(plan{', force=True' if force else ''})")
        return _run(plan, on_progress, force=force)

    def presets(self) -> list[dict]:
        """The presets that can be offered — read-only, hence nothing to echo."""
        return describe_presets()

    # --- frame selection -------------------------------------------------------
    def measures(self, plan: Plan) -> dict:
        """Measurements per group, re-judged — read-only, hence nothing to echo."""
        return _measures(plan)

    def rejects(self, plan: Plan) -> dict:
        """Manual rejections set on the plan — read-only."""
        return _rejects(plan)

    def summary(self, plan: Plan, measured: dict | None = None) -> list[dict]:
        """Real total integration time per group — read-only."""
        return _summary(plan, measured)

    def criteria(self, plan: Plan) -> dict:
        """Criteria set on each group — read-only."""
        return _criteria(plan)

    def set_rejects(self, plan: Plan, group: str, paths) -> Plan:
        result = _set_rejects(plan, group, paths)
        self._echo(f"retina.pipeline.set_rejects(plan, {group!r}, {_format_paths(paths)})")
        return result

    def set_step_params(self, plan: Plan, step_id: str, index: int = 0, **values) -> Plan:
        result = _set_step_params(plan, step_id, index, values)
        args = ", ".join(f"{k}={v!r}" for k, v in values.items())
        self._echo(f"retina.pipeline.set_step_params(plan, {step_id!r}, {index}, dict({args}))")
        return result

    def set_hooks(self, plan: Plan, step_id: str, before=..., after=...) -> Plan:
        result = _set_hooks(plan, step_id, before, after)
        args = ", ".join(f"{name}={value!r}" for name, value in
                         (("before", before), ("after", after)) if value is not ...)
        self._echo(f"retina.pipeline.set_hooks(plan, {step_id!r}, {args})")
        return result

    def hooks(self, plan: Plan) -> dict:
        """Hooks set on the plan — read-only."""
        return _hooks(plan)

    def set_criteria(self, plan: Plan, group: str | None = None, **criteria) -> Plan:
        result = _set_criteria(plan, group, **criteria)
        args = ", ".join(f"{k}={v!r}" for k, v in criteria.items())
        target = "plan" if group is None else f"plan, {group!r}"
        self._echo(f"retina.pipeline.set_criteria({target}, {args})")
        return result

    def __repr__(self) -> str:
        return "app.pipeline (scan · plan · run)"
