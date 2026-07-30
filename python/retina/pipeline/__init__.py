"""End-to-end automated pre-processing — batch pre-processing, in native Python.

Point it at a folder of raw frames (lights/darks/flats/bias) and obtain masters plus one
integrated image per filter, with no intervention:

    import retina
    inventory = retina.pipeline.scan("/data/M31")
    plan = retina.pipeline.plan(inventory, preset="auto")
    print(plan.describe())          # inspectable BEFORE launching
    report = retina.pipeline.run(plan)

The package is **pure domain**: no dependency on the shell, no display. The GUI and the CLI
(``python -m retina.pipeline <folder>``) are two clients of it, on the same footing as the
console — that is the project's parity rule.

Breakdown:

- :mod:`~retina.pipeline.scan` — walking a folder, classifying frames;
- :mod:`~retina.pipeline.groups` — grouping and calibration ↔ lights matching;
- :mod:`~retina.pipeline.presets` — the settings that change from one rig to the next;
- :mod:`~retina.pipeline.plan` — the execution plan, inspectable and editable;
- :mod:`~retina.pipeline.runner` — execution, with cache, progress and cancellation;
- :mod:`~retina.pipeline.selection` — re-read the measurements, re-judge, reject by hand;
- :mod:`~retina.pipeline.measure_cache` — persistent measurement cache, per file;
- :mod:`~retina.pipeline.synthetic` — synthetic raw dataset (tests and demo).
"""

from __future__ import annotations

from .editing import hooks, set_hooks, set_step_params
from .groups import (
    PANEL_SEPARATION,
    CalibrationMatch,
    CalibrationStep,
    FrameGroup,
    Survey,
    angular_separation,
    detect_panels,
    group_frames,
    match_calibration,
    survey,
)
from .measure_cache import MeasureCache, clear_measure_cache
from .plan import Plan, PlanStep, plan
from .presets import PRESETS, Preset, describe_presets
from .runner import RunReport, run
from .scan import FrameInfo, Inventory, classify, exclude, reclassify, scan
from .selection import criteria, measures, rejects, set_criteria, set_rejects
from .selection import describe as describe_selection
from .selection import summary as selection_summary

__all__ = [
    "PANEL_SEPARATION",
    "PRESETS",
    "CalibrationMatch",
    "CalibrationStep",
    "FrameGroup",
    "FrameInfo",
    "Inventory",
    "MeasureCache",
    "Plan",
    "PlanStep",
    "Preset",
    "RunReport",
    "Survey",
    "angular_separation",
    "classify",
    "clear_measure_cache",
    "criteria",
    "describe_presets",
    "describe_selection",
    "detect_panels",
    "exclude",
    "group_frames",
    "hooks",
    "match_calibration",
    "measures",
    "plan",
    "reclassify",
    "rejects",
    "run",
    "scan",
    "selection_summary",
    "set_criteria",
    "set_hooks",
    "set_rejects",
    "set_step_params",
    "survey",
]
