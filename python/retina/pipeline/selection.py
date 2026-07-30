"""Frame selection: re-read the measurements, re-judge, reject by hand.

Pre-processing measures each sub (FWHM, eccentricity, SNR, stars) and derives an integration
weight from it. This module is what allows **going back on that judgement** between two
runs, without re-measuring anything and without interrupting anything.

# Why between two runs, and not during

The established approach opens its selection screen **in the middle of the run**, in a modal
that blocks the pipeline until a decision is made. Our runner is fire-and-forget and stays
so: the measurements being written to disk (``retina_pipeline/measures/<key>.json``), we
re-read them whenever we want, re-judge, and relaunch. There is no pause mechanism to
invent — the absence of a modal *is* the design.

# Re-judging costs nothing, and that is the whole point

:func:`measures` re-reads the JSON then calls :meth:`SubframeSelector.evaluate` again with
the plan's current criteria. Ticking a rejection and seeing the weights move is therefore
instantaneous. The run cache follows the same line (``Process.cache_values``): a manual
rejection invalidates **only** the integration, because the weights enter its fingerprint
through the ``@weights`` late binding. The measurements, the calibration and the
registration, for their part, remain served from the cache.

# Two notions of rejection, not to be confused

*Setting aside from the project* (``retina.pipeline.exclude``) removes a file from **the
whole** chain: wrong type, corrupt, wrong target. It changes the inputs of the calibration,
of the measurement and of the registration — hence invalidates their cache.

*Not stacking this sub* (here) still lets it be calibrated and registered; it simply weighs
zero in the stack. It is the gesture that follows a measurement, and it costs only the
integration.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import TYPE_CHECKING

from ..i18n import translate as _t
from . import cache

if TYPE_CHECKING:
    from .plan import Plan, PlanStep

#: prefix of the measurement steps in a plan
MEASURE_PREFIX = "measure_"


def read_measures(path: str) -> list[dict]:
    """Measurements written by a ``measure_*`` step. Empty list if the file is missing."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def write_measures(path: str, rows: list[dict]) -> None:
    """Writes a group's measurements atomically (never a truncated JSON to read back)."""
    cache.save_atomic(path, lambda tmp: pathlib.Path(tmp).write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"))


def measure_steps(plan: Plan) -> dict[str, PlanStep]:
    """The plan's measurement steps, indexed by group of lights."""
    return {step.group or step.id: step for step in plan.steps
            if step.id.startswith(MEASURE_PREFIX)}


def measures(plan: Plan) -> dict[str, list[dict]]:
    """Measurements of each group, **re-judged** with the plan's current criteria.

    Re-reads the files already produced; a group that was never measured returns an empty
    list rather than raising — inspecting a half-executed plan is a normal case.

    >>> measured = retina.pipeline.measures(plan)
    >>> [m["frame"] for m in measured["light_L_300s_bin1"] if not m["approved"]]
    ['/data/M31/light_007.fits']
    """
    out: dict[str, list[dict]] = {}
    for group, step in measure_steps(plan).items():
        rows = read_measures(step.outputs[0]) if step.outputs else []
        if rows and step.process is not None:
            step.process.evaluate(rows)
        out[group] = rows
    return out


def rejects(plan: Plan) -> dict[str, list[str]]:
    """Manual rejections currently set on the plan, by group."""
    return {group: list(getattr(step.process, "manual_rejects", []) or [])
            for group, step in measure_steps(plan).items()}


def set_rejects(plan: Plan, group: str, paths) -> Plan:
    """Sets the frames excluded from a group's stack. Returns the modified plan.

    ``paths`` replaces the list — it is not an addition. A checkbox toggle therefore sends
    the complete state, which makes the operation idempotent and the plan replayable as is
    (the rejections travel in its JSON serialization).

    >>> retina.pipeline.set_rejects(plan, "light_L_300s_bin1", ["/data/M31/light_007.fits"])
    """
    steps = measure_steps(plan)
    step = steps.get(group)
    if step is None or step.process is None:
        raise KeyError(_t("No measurement step for group {group!r} (known: {known})").format(
            group=group, known=", ".join(sorted(steps)) or _t("none")))
    step.process.manual_rejects = [str(p) for p in paths]
    return plan


#: settings of the selector, and what each costs to change. The first three are re-judged
#: for free; ``roundness_limit`` is a **detection** parameter — touching it redoes the
#: measurements, and the interface must say so rather than let it be discovered.
CRITERIA = ("approval", "weighting", "min_weight", "roundness_limit")

#: those whose change forces a new measurement (cf. ``SubframeSelector.cache_values``)
REMEASURING_CRITERIA = ("roundness_limit",)


def set_criteria(plan: Plan, group: str | None = None, **criteria) -> Plan:
    """Sets the selection criteria of a group, or of all of them if ``group`` is omitted.

    ``group=None`` is the common gesture: one writes a criterion once and it applies to the
    whole night. The established interface has the same button ("apply to all groups"), and
    for the same reason — an FWHM threshold is meaningless filter by filter.

    >>> retina.pipeline.set_criteria(plan, approval="eccentricity < 0.6")
    """
    unknown_items = set(criteria) - set(CRITERIA)
    if unknown_items:
        raise ValueError(_t("Unknown criteria: {unknown} (available: {available})").format(
            unknown=sorted(unknown_items), available=list(CRITERIA)))
    # A faulty expression is refused **before** entering the plan. Stored, it would make any
    # re-read of the measurements fail — the selection screen would become unusable until
    # the plan was repaired by hand.
    from ..processes.subframe import validate_expression

    for name in ("approval", "weighting"):
        if name in criteria:
            problem = validate_expression(str(criteria[name] or ""))
            if problem:
                raise ValueError(_t("{name}: {problem}").format(name=name, problem=problem))
    steps = measure_steps(plan)
    targets = steps if group is None else {group: steps.get(group)}
    for key, step in targets.items():
        if step is None or step.process is None:
            raise KeyError(
                _t("No measurement step for group {group!r} (known: {known})").format(
                    group=key, known=", ".join(sorted(steps)) or _t("none")))
        for name, value in criteria.items():
            setattr(step.process, name, value)
    return plan


def criteria(plan: Plan) -> dict[str, dict]:
    """Criteria currently set on each group."""
    return {group: {name: getattr(step.process, name) for name in CRITERIA}
            for group, step in measure_steps(plan).items() if step.process is not None}


def summary(plan: Plan, measured: dict[str, list[dict]] | None = None) -> list[dict]:
    """What each group will return *after* selection — real integration time included.

    ``Plan.products`` announces an **upper bound**: it counts the inputs of the integration,
    and a rejected frame stays an input, it simply weighs zero. The number one wants to read
    therefore comes from the measurements, not from the plan — it is what melts the night
    from 4 h down to 3 h 20 when six subs are set aside, and it is that visual feedback
    which justifies sorting.
    """
    measured_rows = measures(plan) if measured is None else measured
    out = []
    for product in plan.products:
        rows = measured_rows.get(product.key, [])
        approved = [m for m in rows if m.get("approved", True)]
        # without a measurement, we know nothing more than the plan: we repeat its bound
        kept_rows = len(approved) if rows else product.frames
        patterns: dict[str, int] = {}
        for m in rows:
            if not m.get("approved", True):
                pattern = str(m.get("rejected_by") or "unknown")
                patterns[pattern] = patterns.get(pattern, 0) + 1
        out.append({
            "key": product.key,
            "filter": product.filter,
            "path": product.path,
            "exposure": product.exposure,
            "planned": product.frames,
            "measured": len(rows),
            "frames": kept_rows,
            "rejected": len(rows) - len(approved) if rows else 0,
            "rejected_by": patterns,
            "integration": None if product.exposure is None else kept_rows * product.exposure,
        })
    return out


def describe(plan: Plan, measured: dict[str, list[dict]] | None = None) -> str:
    """Selection summary as text, for the console and the CLI."""
    from .plan import _duration

    lines = []
    for row in summary(plan, measured):
        frame = ("" if row["integration"] is None
                else f" = {_duration(row['integration'])}")
        detail = ", ".join(f"{n} {pattern}" for pattern, n in sorted(row["rejected_by"].items()))
        rejection = f" — {row['rejected']} set aside ({detail})" if row["rejected"] else ""
        lines.append(f"{row['key']}: {row['frames']}/{row['measured'] or row['planned']}"
                      f" sub(s){frame}{rejection}")
    return "\n".join(lines)


def measures_path(plan: Plan, group: str) -> str | None:
    """Measurement file of a group, if the plan provides for one."""
    step = measure_steps(plan).get(group)
    return step.outputs[0] if step is not None and step.outputs else None


def has_measures(plan: Plan) -> bool:
    """True if at least one measurement file exists — the selector has something to work on."""
    return any(os.path.exists(s.outputs[0])
               for s in measure_steps(plan).values() if s.outputs)
