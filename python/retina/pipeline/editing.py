"""Editing an already built plan: adjusting a step, hooking scripts onto it.

A plan is serializable and replayable end to end (``PlanStep.to_dict``/``from_dict`` are
symmetric): adjusting it therefore has nothing to invent, it is enough to replace one
process instance with another. This module is what the console and the wizard both call — a
`plan.steps[i].process.x = y` typed by hand works too, but without validation.

# Why validate here rather than let it through

``Process.__init__`` refuses unknown parameters and converts types, but it checks **neither
the bounds nor the enumeration choices**: `sigma=-4` or `method="guesswork"` get in without
a sound and fail only after three hours of computation, in a thread, with a message that
does not say where the value came from. Validation is therefore done at the moment the user
types, against the same schema as the auto-generated form.

# What is not editable

**Bound** parameters (``PlanStep.bindings``: ``@reference``, ``@weights``) are resolved by
the runner at run time — writing them into the plan would be a lie, the value set would be
overwritten. They are refused explicitly rather than ignored.

And **the list of steps is not modifiable**: it is the contract of the preset, and the plan
is a graph in which the ``inputs`` of a step are the ``outputs`` of the previous one.
Disabling registration would leave the integration reading files nobody writes. To change
the composition of the plan, one changes the preset and rebuilds — it is immediate, and the
result stays consistent. (If the need for a per-step switch appears, the delta is known:
serialize the recipe through ``to_dicts``/``from_dicts`` to preserve the ``ProcessContainer``
``enabled`` flags, skip the step in ``_run_per_frame``, and make the flag enter the cache
fingerprint.)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from ..i18n import translate as _t
from ..process.base import Parameter

if TYPE_CHECKING:
    from .plan import Plan, PlanStep

#: phases to which a script can be hooked
HOOK_PHASES = ("before", "after")


def _step(plan: Plan, step_id: str) -> PlanStep:
    step = plan.step(step_id)
    if step is None:
        raise KeyError(_t("Unknown step {step!r} (known: {known})").format(
            step=step_id, known=", ".join(s.id for s in plan.steps)))
    return step


def _check(param: Parameter, value: Any) -> None:
    """Bounds and choices — what ``Parameter.coerce`` does not look at."""
    if param.choices is not None and value not in param.choices:
        raise ValueError(_t("{name}: {value!r} is not one of {choices}").format(
            name=param.id, value=value, choices=list(param.choices)))
    if param.type in ("int", "real"):
        if param.min is not None and value < param.min:
            raise ValueError(_t("{name}: {value} is below the minimum {limit}").format(
                name=param.id, value=value, limit=param.min))
        if param.max is not None and value > param.max:
            raise ValueError(_t("{name}: {value} is above the maximum {limit}").format(
                name=param.id, value=value, limit=param.max))


def set_step_params(plan: Plan, step_id: str, index: int, values: dict) -> Plan:
    """Sets the parameters of one process of a step. Returns the modified plan.

    ``index`` is the position in ``step.processes`` — a recipe may carry the same process
    twice, and the identifier alone would not distinguish them.

    ``values`` is a **partial update**: the parameters that are absent keep their value. The
    instance is rebuilt rather than mutated, so that type conversion and the refusal of
    unknown parameters go through the same path as a normal creation.

    >>> retina.pipeline.set_step_params(plan, "calibrate_light_L", 0, {"pedestal_mode": "none"})
    """
    step = _step(plan, step_id)
    processes = step.processes
    if not 0 <= index < len(processes):
        raise IndexError(_t("Step {step!r} has {count} process(es), no index {index}").format(
            step=step_id, count=len(processes), index=index))
    process = processes[index]

    linked = set(values) & set(step.bindings)
    if linked:
        raise ValueError(_t("{names}: resolved at run time ({tokens}), cannot be set").format(
            names=sorted(linked), tokens=", ".join(step.bindings[k] for k in sorted(linked))))

    schema = {p.id: p for p in type(process).parameters}
    unknown_items = set(values) - set(schema)
    if unknown_items:
        raise ValueError(_t("{process_id}: unknown parameters {names}").format(
            process_id=process.process_id, names=sorted(unknown_items)))

    # Candidate rebuild: `coerce` converts, `_check` bounds. The plan is touched only once
    # both have passed — a refusal leaves the step exactly in its state.
    merge = {**process.values(), **values}
    candidate = type(process)(**merge)
    for name in values:
        _check(schema[name], getattr(candidate, name))

    if step.recipe is not None:
        step.recipe.processes[index] = candidate
    else:
        step.process = candidate
    return plan


def set_hooks(plan: Plan, step_id: str, before: str | None = ..., after: str | None = ...) -> Plan:
    """Hooks a Python script before and/or after a step. Returns the modified plan.

    This is the equivalent of *event scripts*, in Python rather than in an extension
    language. The script is run by the :class:`~retina.processes.script.Script` process — it
    therefore inherits its SHA-256 digest, its cancellation and its echo. The step's context
    (identifier, group, inputs, outputs) reaches it through ``retina.parameters``.

    Passing ``None`` removes the hook; omitting an argument leaves it as it is.

    >>> retina.pipeline.set_hooks(plan, "integrate_light_L", after="~/scripts/publish.py")
    """
    step = _step(plan, step_id)
    for phase, value in (("before", before), ("after", after)):
        if value is ...:
            continue
        if value in (None, ""):
            step.hooks.pop(phase, None)
            continue
        path = os.path.expanduser(str(value))
        if not os.path.isfile(path):
            raise FileNotFoundError(_t("Hook script not found: {path}").format(path=path))
        step.hooks[phase] = path
    return plan


def hooks(plan: Plan) -> dict[str, dict[str, str]]:
    """Hooks set on the plan, by step (the steps without a hook are omitted)."""
    return {step.id: dict(step.hooks) for step in plan.steps if step.hooks}
