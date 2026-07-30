"""``pipeline.*`` family — automated preprocessing, exposed to the frontend.

Like every handler family, this one contains **no logic**: it transports, validates the
minimum, and delegates to ``app.pipeline`` — which runs the domain and emits the Python echo.
The wizard therefore has no power of its own, and every gesture it makes is written to the
console as replayable code.

Three calls carry the thread, in the order the wizard chains them: ``scan`` (what does this
folder hold?), ``plan`` (what are we going to do?), ``run`` (do it). The first two return
their result directly, the third a job id — a preprocessing run takes hours. Between the scan
and the plan, ``survey`` says what the domain grouped and which masters it pairs — the
frontend recomputes none of those rules — while ``reclassify`` and ``exclude`` allow
correcting the inventory: classification is a deduction, and it gets things wrong.

``scan`` is **asynchronous** and offloaded to the pool: reading the headers of five hundred
files takes several seconds, and blocking the asyncio loop would freeze all the rest of the
interface.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .rpc import DOMAIN_ERROR, RpcError

if TYPE_CHECKING:
    from concurrent.futures import Executor

    from ..app import Application
    from .jobs import JobRunner

#: name under which the pipeline appears in the job list
PIPELINE_JOB = "Pipeline"

PIPELINE_METHODS: dict[str, bool] = {
    "pipeline.presets": False,
    "pipeline.scan": False,
    # grouping + master pairing: what the wizard displays per group
    "pipeline.survey": False,
    # the wizard's corrections to the inventory — the state lives on the client, which passes
    # the corrected inventory back to `plan`; the server keeps nothing.
    "pipeline.reclassify": False,
    "pipeline.exclude": False,
    "pipeline.plan": False,
    # frame selection: read back the measurements of a past run and rejudge. As for the
    # inventory, the state lives on the client — it passes the corrected plan back to `run`.
    "pipeline.measures": False,
    "pipeline.set_rejects": False,
    "pipeline.set_criteria": False,
    # plan editing: tune a step, hook a script onto it. Same contract as above — the
    # corrected plan goes back to the client, the server keeps nothing.
    "pipeline.set_step_params": False,
    "pipeline.set_hooks": False,
    # `run` returns a job id immediately; the snapshot goes out at the *end*, not here.
    "pipeline.run": False,
    "pipeline.report": False,
}


class PipelineHandlers:
    def __init__(self, app: Application, runner: JobRunner, executor: Executor) -> None:
        self._app = app
        self._runner = runner
        self._executor = executor
        #: last run report, to be fetched once the job is finished
        self._report: dict | None = None

    def presets(self) -> list[dict]:
        return self._app.pipeline.presets()

    async def scan(self, path: str, recursive: bool = True) -> dict:
        """Inventories a folder. Offloaded to the pool: this is I/O, and there is a lot."""
        loop = asyncio.get_running_loop()
        try:
            inventory = await loop.run_in_executor(
                self._executor, lambda: self._app.pipeline.scan(path, recursive=recursive))
        except ValueError as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return inventory.to_dict()

    def survey(self, inventory: dict, preset: str | dict | None = None) -> dict:
        """Detected groups and paired masters — the table the wizard displays.

        Grouping is done **here**, by the domain, and not approximated on the TypeScript
        side: the keys displayed are then the ones the plan will use, and each group's
        calibration status comes from the same pairing as the run.
        """
        from ..pipeline.scan import Inventory

        return self._app.pipeline.survey(Inventory.from_dict(inventory), preset).to_dict()

    def reclassify(self, inventory: dict, paths: list[str], kind: str) -> dict:
        """Corrects the type of misdetected frames and returns the updated inventory."""
        from ..pipeline.scan import Inventory

        try:
            corrected = self._app.pipeline.reclassify(
                Inventory.from_dict(inventory), list(paths), kind)
        except ValueError as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return corrected.to_dict()

    def exclude(self, inventory: dict, paths: list[str], excluded: bool = True) -> dict:
        """Drops (or reinstates) frames and returns the updated inventory."""
        from ..pipeline.scan import Inventory

        try:
            corrected = self._app.pipeline.exclude(
                Inventory.from_dict(inventory), list(paths), bool(excluded))
        except ValueError as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return corrected.to_dict()

    def plan(self, inventory: dict, preset: str | dict = "auto",
             output_dir: str | None = None, groups: list[dict] | None = None) -> dict:
        """Builds the execution plan. Nothing is written to disk at this stage."""
        from ..pipeline.groups import FrameGroup
        from ..pipeline.scan import Inventory

        try:
            batches = [FrameGroup.from_dict(g) for g in groups] if groups is not None else None
            plan = self._app.pipeline.plan(Inventory.from_dict(inventory), preset,
                                           output_dir=output_dir, groups=batches)
        except (ValueError, KeyError) as exc:
            raise RpcError(DOMAIN_ERROR, f"Cannot plan: {exc}") from None
        return plan.to_dict()

    # --- frame selection -------------------------------------------------------
    def _plan(self, plan: dict):
        from ..pipeline.plan import Plan

        try:
            return Plan.from_dict(plan)
        except (KeyError, ValueError, TypeError) as exc:
            raise RpcError(DOMAIN_ERROR, f"Invalid plan: {exc}") from None

    def measures(self, plan: dict) -> dict:
        """Per-group measurements, **rejudged** with the plan's current criteria.

        Neither asynchronous nor offloaded: this is reading one JSON per group followed by an
        expression evaluation, on the order of a millisecond. That is exactly what the
        measure/evaluate decoupling buys — ticking a rejection and seeing the weights move
        without remeasuring anything.
        """
        instance = self._plan(plan)
        try:
            measures = self._app.pipeline.measures(instance)
        except ValueError as exc:
            # A plan loaded from a hand-written JSON can carry a faulty expression that
            # `set_criteria` has never seen: without this net, the selection screen would
            # return an internal error instead of saying what is wrong.
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return {
            "groups": measures,
            "rejects": self._app.pipeline.rejects(instance),
            "criteria": self._app.pipeline.criteria(instance),
            "summary": self._app.pipeline.summary(instance, measures),
        }

    def set_rejects(self, plan: dict, group: str, paths: list[str]) -> dict:
        """Sets the frames dropped from a group's stacking and returns the updated plan.

        ``paths`` replaces the list: a toggle sends the complete state, so the call is
        idempotent and the plan stays replayable as is.
        """
        instance = self._plan(plan)
        try:
            corrected = self._app.pipeline.set_rejects(instance, group, list(paths))
        except KeyError as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return corrected.to_dict()

    def set_criteria(self, plan: dict, group: str | None = None,
                     criteria: dict | None = None) -> dict:
        """Tunes the selection criteria (expressions, floor, roundness tolerance).

        Omitting ``group`` applies them to every group — that is the usual gesture: an FWHM
        threshold makes no sense filter by filter.
        """
        instance = self._plan(plan)
        try:
            corrected = self._app.pipeline.set_criteria(instance, group, **(criteria or {}))
        except (KeyError, ValueError) as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return corrected.to_dict()

    def set_step_params(self, plan: dict, step_id: str, index: int = 0,
                        values: dict | None = None) -> dict:
        """Tunes the parameters of a step's process and returns the updated plan.

        ``index`` designates the position within the step's recipe: a recipe can carry the
        same process twice, and the id alone would not tell them apart.
        """
        instance = self._plan(plan)
        try:
            corrected = self._app.pipeline.set_step_params(
                instance, step_id, index, **(values or {}))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return corrected.to_dict()

    def set_hooks(self, plan: dict, step_id: str, before: str | None = None,
                  after: str | None = None) -> dict:
        """Hooks (or removes, with ``null``) the scripts run around a step."""
        instance = self._plan(plan)
        try:
            corrected = self._app.pipeline.set_hooks(instance, step_id, before, after)
        except (KeyError, OSError, ValueError) as exc:
            raise RpcError(DOMAIN_ERROR, str(exc)) from None
        return corrected.to_dict()

    def run(self, plan: dict) -> dict:
        """Starts the preprocessing run in the background and returns its job id."""
        instance = self._plan(plan)
        if not instance.steps:
            raise RpcError(DOMAIN_ERROR, "Empty plan: nothing to run")
        # One preprocessing run at a time: the thread pool is shared with the viewport and
        # the statistics, and two runs would write into the same files.
        if self._runner.has_active(PIPELINE_JOB):
            raise RpcError(DOMAIN_ERROR, "A preprocessing run is already in progress")

        self._report = None

        def work() -> dict:
            # The report travels with the final notification (`job.done`): the client knows
            # what was produced without having to poll, and two connected clients receive
            # the same thing. `pipeline.report` stays there for whoever arrives afterwards.
            report = self._app.pipeline.run(instance)
            self._report = report.to_dict()
            return self._report

        return {"job": self._runner.submit_call(work, PIPELINE_JOB)}

    def report(self) -> dict | None:
        """Report of the last preprocessing run, or ``None`` if it has not completed yet."""
        return self._report
