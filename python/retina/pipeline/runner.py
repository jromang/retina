"""Execution of a plan: file → file, with cache, progress and cancellation.

The runner is deliberately **sequential and on disk**. Sequential because it runs in a
single worker (the server's thread pool is shared with the viewport and the statistics:
launching thirty subtasks in it would bring the interface down). On disk because a hundred
50 Mpx lights do not fit in memory, because resuming after an interruption becomes free, and
because every intermediate opens in Retina to be inspected.

# What the runner decides, and that the plan could not know

``@reference``
    The reference frame for registration: the one showing **the most stars**, taken from
    among the finest binning. The criterion is the usual one, and it is not intuitive — one
    would gladly take the best FWHM, but what one wants from a reference is the largest
    number of landmarks to match, not the prettiest image. It is **common to every group**:
    failing which the L, R, G, B layers would not superimpose.

    A **mosaic** is the only exception, and it proves the rule: each panel has its own. The
    reason for a common reference is that the layers must superimpose to the pixel; between
    two panels looking at disjoint fields, it reverses — registering one on the other's
    reference would require matching stars that have no reason to be the same ones.

``@weights``
    The group's integration weights, derived from ``SubframeSelector``.

# One frame that fails does not carry off the batch

A truncated file, a sub on which star matching does not converge: over several hundred
frames, that **happens**. Interrupting three hours of computation for one frame out of two
hundred would be the worst possible behavior — the user wants the other hundred and
ninety-nine. The offending frame is therefore set aside, the reason recorded in the report,
and the following steps no longer see it. Only an explicit cancellation
(:class:`ProcessCancelled`) really interrupts, and an entirely lost group raises.

# Progress

Each step receives a share of the bar proportional to its number of frames, via a
:class:`~retina.process.progress.ScaledMonitor`. Instrumented processes pour their progress
into it without knowing anything about the pipeline; the runner adds its own (frame i/N).
Since ``ProgressMonitor.report`` makes a cancellation point, instrumenting gives
cancellation.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np

from ..i18n import translate as _t
from ..process import context
from ..process.progress import ProcessCancelled, ProgressMonitor, ScaledMonitor
from . import cache, selection
from .plan import REFERENCE, WEIGHTS, Plan, PlanStep

ProgressCallback = Callable[[float | None, str], None]


@contextmanager
def _sub_progress(parent: ProgressMonitor, offset: float, span: float):
    """Installs a progress window in thread-local storage, for the duration of a block."""
    previous = context.get_monitor()
    context.set_monitor(ScaledMonitor(parent, offset, span))
    try:
        yield
    finally:
        context.set_monitor(previous)


@dataclass
class RunReport:
    """What the run produced — and what it managed to avoid doing over again."""

    output_dir: str
    #: ``{step id: main output}``
    outputs: dict[str, str] = field(default_factory=dict)
    #: steps served from the cache
    skipped: list[str] = field(default_factory=list)
    #: steps actually executed
    executed: list[str] = field(default_factory=list)
    #: measurements per group (``SubframeSelector``)
    measurements: dict[str, list[dict]] = field(default_factory=dict)
    #: what each group really returned — total integration time **after** selection, where
    #: ``Plan.products`` could only announce an upper bound (see :mod:`.selection`)
    products: list[dict] = field(default_factory=list)
    #: reference frame retained for registration
    reference: str | None = None
    #: decisions and anomalies met along the way
    notes: list[str] = field(default_factory=list)

    @property
    def results(self) -> list[str]:
        """The final images — one per group of lights, as delivered.

        Astrometric solving then cropping are the last hands laid on: that image is the
        result, not the integrated image with incomplete edges that preceded it.
        """
        for prefix in ("platesolve_", "autocrop_"):
            last = [v for k, v in self.outputs.items() if k.startswith(prefix)]
            if last:
                return last
        return [v for k, v in self.outputs.items() if k.startswith("integrate_")]

    def describe(self) -> str:
        lines = [f"{len(self.executed)} step(s) executed, "
                  f"{len(self.skipped)} served from the cache"]
        if self.reference:
            lines.append(f"  reference: {os.path.basename(self.reference)}")
        for note in self.notes:
            lines.append(f"  · {note}")
        for product in self.products:
            from .plan import _duration

            frame = ("" if product["integration"] is None
                    else f" — {product['frames']} × {product['exposure']:g} s = "
                         f"{_duration(product['integration'])}")
            rejected = f" ({product['rejected']} set aside)" if product["rejected"] else ""
            lines.append(f"  {os.path.basename(product['path'])}{frame}{rejected}")
        for result in self.results:
            lines.append(f"  → {result}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "output_dir": self.output_dir, "outputs": dict(self.outputs),
            "skipped": list(self.skipped), "executed": list(self.executed),
            "measurements": dict(self.measurements), "reference": self.reference,
            "products": list(self.products),
            "notes": list(self.notes), "results": self.results,
        }


class _Runner:
    def __init__(self, plan: Plan, monitor: ProgressMonitor, force: bool) -> None:
        self.plan = plan
        self.monitor = monitor
        self.force = force
        self.report = RunReport(output_dir=plan.output_dir)
        #: measurements per group, fed by the ``measure_*`` steps
        self.measurements: dict[str, list[dict]] = {}
        self.reference: str | None = None
        #: reference per mosaic panel (``{number: file}``). See `_choose_reference`.
        self.panel_references: dict[int, str] = {}
        #: outputs that could not be produced — the following steps ignore them
        self.failed: set[str] = set()

    # --- inputs/outputs --------------------------------------------------------
    @staticmethod
    def _load(path: str):
        from ..io.fits import load_fits
        from ..model.image import Image

        if os.path.splitext(path)[1].lower() in (".fits", ".fit", ".fts"):
            return load_fits(path)
        from ..io import load_image_array

        return Image(load_image_array(path)), {}

    @staticmethod
    def _save(path: str, image, keywords: dict, step: PlanStep) -> None:
        from ..io.fits import save_fits

        # we inherit the source keywords (filter, exposure, temperature: the grouping of a
        # later run depends on them) and trace the step, as a FITS HISTORY would.
        outgoing = {k: v for k, v in keywords.items()
                    if k not in ("NAXIS", "NAXIS1", "NAXIS2", "NAXIS3", "BITPIX",
                                 "SIMPLE", "EXTEND")}
        outgoing.update(step.keywords)  # a master's identity: it wins over inheritance
        outgoing["HISTORY"] = f"retina.pipeline {step.id}"
        cache.save_atomic(path, lambda tmp: save_fits(tmp, image, outgoing))

    @staticmethod
    def _inherited(step: PlanStep) -> dict:
        """Keywords of the first input — the identity common to the batch."""
        if not step.inputs:
            return {}
        from ..io.fits import load_fits_header

        try:
            return load_fits_header(step.inputs[0])
        except Exception:
            return {}

    # --- late bindings ---------------------------------------------------------
    def _resolved_for(self, step: PlanStep) -> dict:
        """Concrete values of the tokens declared by the step."""
        out: dict = {}
        for param, token in step.bindings.items():
            if token == REFERENCE:
                out[param] = self._reference_for(step)
            elif token == WEIGHTS:
                out[param] = self._weights_for(step.group, len(step.inputs))
            else:
                raise ValueError(_t("{step}: unknown late binding {token!r}").format(
                    step=step.id, token=token))
        return out

    def _weights_for(self, group: str | None, count: int) -> list[float]:
        measures = self.measurements.get(group or "", [])
        weights = [float(m.get("weight", 0.0)) for m in measures]
        rejected_items = [m for m in measures if not m.get("approved", True)]
        if rejected_items:
            # say *why*, not only how many: "set aside" without a reason forces reopening
            # the selector to tell a manual rejection from an automatic threshold.
            patterns: dict[str, int] = {}
            for m in rejected_items:
                pattern = str(m.get("rejected_by") or "expression")
                patterns[pattern] = patterns.get(pattern, 0) + 1
            detail = ", ".join(f"{n} {pattern}" for pattern, n in sorted(patterns.items()))
            self.report.notes.append(
                _t("{group}: {count} frame(s) excluded from stacking ({detail})").format(
                    group=group, count=len(rejected_items), detail=detail))
        if len(weights) != count or sum(weights) <= 0.0:
            # measurements missing or out of sync (frames rejected in the meantime): we
            # prefer a uniform integration, announced as such, to arbitrary weights.
            self.report.notes.append(
                _t("{group}: weights unavailable, uniform integration").format(group=group))
            return []
        return weights

    def _apply_bindings(self, step: PlanStep, resolved: dict) -> None:
        """Sets the resolved values on the step's processes that declare them."""
        for param, value in resolved.items():
            if value is None:
                raise ValueError(
                    _t("{step}: {param} unresolved (no reference available)").format(
                        step=step.id, param=param))
            for process in step.processes:
                if any(p.id == param for p in process.parameters):
                    setattr(process, param, value)

    def _panel_of(self, group: str | None) -> int:
        """Panel number of a group, read from its key (``…_panel2``). 0 = no mosaic."""
        if not group:
            return 0
        for part in group.split("_"):
            if part.startswith("panel") and part[5:].isdigit():
                return int(part[5:])
        return 0

    def _reference_for(self, step: PlanStep) -> str | None:
        """Registration reference of this step — that of its panel if there is one."""
        panel = self._panel_of(step.group)
        if panel:
            return self.panel_references.get(panel) or self.reference
        return self.reference

    @staticmethod
    def _best(measures: list[dict]) -> dict | None:
        approved = [m for m in measures if m.get("approved", True)]
        if not approved:
            return None
        return max(approved, key=lambda m: (m.get("stars", 0), -m.get("fwhm", 0.0)))

    def _choose_reference(self) -> None:
        """The frame showing the most stars — **per panel**, otherwise globally.

        The usual rule is a single reference for the whole batch, and its reason is that the
        L/R/G/B layers must superimpose to the pixel. That reason holds inside a mosaic
        panel; between panels it reverses. Two panels look at disjoint fields: registering
        one on the other's reference means asking `astroalign` to match stars that have no
        reason to be the same ones — at best a failure, at worst an empty canvas that no
        message denounces.
        """
        by_panel: dict[int, list[dict]] = {}
        for group, measures in self.measurements.items():
            by_panel.setdefault(self._panel_of(group), []).extend(measures)

        global_steps = [m for measures in by_panel.values() for m in measures]
        best = self._best(global_steps)
        if best is None:
            return
        self.reference = best.get("frame")
        self.report.reference = self.reference
        self.report.notes.append(
            _t("registration reference: {file} ({stars} stars)").format(
                file=os.path.basename(self.reference or ""),
                stars=best.get("stars", 0)))

        panels = sorted(p for p in by_panel if p)
        if not panels:
            return
        for number in panels:
            choice = self._best(by_panel[number])
            if choice is None:
                continue
            self.panel_references[number] = choice.get("frame") or ""
            self.report.notes.append(
                _t("panel {panel}: registration reference {file} ({stars} stars)").format(
                    panel=number, file=os.path.basename(choice.get("frame") or ""),
                    stars=choice.get("stars", 0)))

    # --- executing a step ------------------------------------------------------
    def _run_per_frame(self, step: PlanStep, progress: ProgressMonitor) -> None:
        """One frame after another, each process in its own slice of the bar.

        The nesting is not decorative: an instrumented process reports *its* progress from 0
        to 1. Without a dedicated window, the third process of the second frame would push
        the bar back to zero. Each therefore receives the share that is due to it — the step
        is cut into frames, the frame into processes.
        """
        total = len(step.inputs)
        steps = max(1, len(step.recipe.processes))
        lost: list[int] = []
        # Registration stars cached per file (StarCache): sep detection per frame is the
        # dominant cost of a registration — serving it again makes a re-run nearly free,
        # and adding a night only re-detects the new subs. The reference, for its part, is
        # detected ONCE per step (and not per frame).
        aligners = [p for p in step.recipe.processes
                     if getattr(p, "process_id", "") == "StarAlignment"
                     and getattr(p, "reference_path", "")]
        star_cache = None
        if aligners:
            from .file_cache import StarCache

            star_cache = StarCache()
            for aligner in aligners:
                aligner.reference_stars = self._alignment_stars(
                    aligner.reference_path, None, star_cache)
        for index, (entry, output) in enumerate(zip(step.inputs, step.outputs,
                                                     strict=True)):
            progress.report(index / total, f"{step.label} — frame {index + 1}/{total}")
            try:
                image, keywords = self._load(entry)
                for aligner in aligners:
                    aligner.source_stars = self._alignment_stars(
                        entry, image, star_cache)
                for rank, process in enumerate(step.recipe.processes):
                    with _sub_progress(progress, (index + rank / steps) / total,
                                  1 / (total * steps)):
                        image = process.execute_on_image(image)
                self._save(output, image, keywords, step)
            except ProcessCancelled:
                raise  # a requested cancellation is not a frame failure
            except Exception as exc:
                self.failed.add(output)
                lost.append(index)
                self.report.notes.append(
                    _t("{step}: {file} excluded — {error}").format(
                        step=step.id, file=os.path.basename(entry),
                        error=f"{type(exc).__name__}: {exc}"))
        if star_cache is not None:
            star_cache.flush()
        if lost and len(lost) == total:
            raise RuntimeError(
                _t("{step}: no frame could be processed").format(step=step.id))
        if lost:
            self._drop_measurements(step.group, total, lost)
        progress.report(1.0, step.label)

    @staticmethod
    def _alignment_stars(path: str, image, cache) -> list | None:
        """Registration stars of a file — from the cache, otherwise detected then stored.

        ``image`` avoids a reload when the frame is already in hand (``None`` for the
        reference, loaded here only once per step). Returns ``None`` if detection fails or
        finds too few stars: ``StarAlignment`` then falls back on its internal detection —
        the cache is a speed-up, never a condition.
        """
        from ..processes.registration import ALIGN_STARS_SETTINGS, detect_alignment_stars

        entry = cache.get(path, ALIGN_STARS_SETTINGS)
        if entry is not None:
            stars = entry.get("stars")
            if isinstance(stars, list) and len(stars) >= 3:
                return stars
        try:
            if image is None:
                from ..io import load_image_array

                data = load_image_array(path)
            else:
                data = image.data if hasattr(image, "data") else image
            stars = detect_alignment_stars(np.asarray(data).mean(axis=2))
        except Exception:
            return None
        if len(stars) < 3:
            return None
        cache.put(path, ALIGN_STARS_SETTINGS, {"stars": stars})
        return stars

    def _drop_measurements(self, group: str | None, total: int,
                           lost: list[int]) -> None:
        """Keeps the measurements aligned with the surviving frames.

        Weights are matched by position: leaving an orphan measurement would put the whole
        list out of sync and the integration would fall back on uniform weights without
        anyone knowing why.
        """
        measures = self.measurements.get(group or "")
        if not measures or len(measures) != total:
            return
        self.measurements[group or ""] = [m for i, m in enumerate(measures)
                                          if i not in set(lost)]

    def _run_global(self, step: PlanStep, progress: ProgressMonitor) -> None:
        process = step.process
        progress.report(0.0, step.label)
        if step.id.startswith("platesolve_"):
            self._solve(step, progress)
            return
        if step.id.startswith("measure_"):
            measures = process.measure()
            self.measurements[step.group or step.id] = measures
            selection.write_measures(step.outputs[0], measures)
            progress.report(1.0, step.label)
            return
        # Integration: `combine()` returns the array without going through a window — the
        # pipeline is headless, it has no application at hand.
        from ..model.image import Image

        data = process.combine()
        # An integrated image inherits the keywords of its inputs. Losing them would deliver
        # a final image with no exposure, no filter and no instrument: unverifiable,
        # ungroupable by a later run, and unusable by anything that reads a header next.
        self._save(step.outputs[0], Image(data), self._inherited(step), step)
        progress.report(1.0, step.label)

    def _skip_failed(self, step: PlanStep) -> None:
        """Removes from a step the inputs a previous step did not produce."""
        if not self.failed:
            return
        if step.kind == "per_frame" and len(step.outputs) == len(step.inputs):
            paires = [(e, s) for e, s in zip(step.inputs, step.outputs, strict=True)
                      if e not in self.failed]
            # The output of a discarded input will never be produced: it joins the blocklist,
            # failing which the *next* step would ask for it. The disappearance has to
            # propagate along the chain, not stop at the first link.
            self.failed.update(s for e, s in zip(step.inputs, step.outputs, strict=True)
                               if e in self.failed)
            step.inputs = [e for e, _ in paires]
            step.outputs = [s for _, s in paires]
        else:
            step.inputs = [e for e in step.inputs if e not in self.failed]
        if not step.inputs:
            raise RuntimeError(_t("{step}: no inputs left").format(step=step.id))
        # A global process carries its own list of frames, frozen at planning time:
        # filtering `step.inputs` without updating it would make it read missing files.
        # Restricted to globals: in a per-frame step, `frames` denotes something other than
        # the inputs (AutoCrop puts the registered ones there to measure their coverage).
        if step.kind == "global":
            for process in step.processes:
                if any(param.id == "frames" for param in process.parameters):
                    process.frames = list(step.inputs)

    def _prune_frame_lists(self, step: PlanStep) -> None:
        """Removes from the auxiliary ``frames`` lists the files that were never produced."""
        for process in step.processes:
            frames = getattr(process, "frames", None)
            if frames and step.kind == "per_frame":
                process.frames = [f for f in frames if f not in self.failed]

    def _solve(self, step: PlanStep, progress: ProgressMonitor) -> None:
        """Solves the final image and writes its WCS into the header.

        A failure never interrupts the batch: missing astrometry deprives one of annotation
        and of mosaicking, it does not make the image wrong. The image is therefore copied
        over as is and the reason recorded — the opposite of a failed calibration, which
        would have to be flagged loudly.
        """
        progress.report(0.0, step.label)
        image, keywords = self._load(step.inputs[0])
        try:
            wcs = step.process.solve(image)
            keywords = dict(keywords)
            keywords.update({k: v for k, v in dict(wcs.to_header()).items() if k})
            self.report.notes.append(
                _t("{group}: astrometry solved").format(group=step.group))
        except Exception as exc:
            self.report.notes.append(
                _t("{group}: astrometry not solved — {error}").format(
                    group=step.group, error=f"{type(exc).__name__}: {exc}"))
        self._save(step.outputs[0], image, keywords, step)
        progress.report(1.0, step.label)

    def _run_hook(self, step: PlanStep, phase: str) -> None:
        """Runs the script hooked to this phase, if there is one.

        The hook is a ``Script`` process: it inherits its verified digest, its cancellation
        and its echo, rather than a parallel extension mechanism. The step's context reaches
        it through ``retina.parameters`` — it reads there the identifier, the group, and
        above all the input and output paths, which are what interest it.

        A hook that raises interrupts the step: it was placed there to do something, and
        carrying on silently after its failure would be worse than never having written it.
        In particular, ``after`` runs **before** the cache is sealed — a step whose hook
        failed therefore remains to be replayed.
        """
        path = step.hooks.get(phase)
        if not path:
            return
        from ..processes.script import Script, file_digest

        hook_globals = {
            "step_id": step.id, "phase": phase, "group": step.group,
            "inputs": list(step.inputs), "outputs": list(step.outputs),
            "output_dir": self.plan.output_dir,
        }
        hook = Script(path=path, digest=file_digest(path),
                         exported_values=json.dumps(hook_globals, ensure_ascii=False))
        self.report.notes.append(
            _t("{step}: {phase} hook — {path}").format(
                step=step.id, phase=phase, path=os.path.basename(path)))
        hook.execute_global(context.get_application())

    def _run_step(self, step: PlanStep, offset: float, span: float) -> None:
        self._skip_failed(step)
        self._prune_frame_lists(step)
        resolved = self._resolved_for(step)
        self._apply_bindings(step, resolved)

        if not self.force and cache.is_fresh(step, resolved):
            self.report.skipped.append(step.id)
            if step.outputs:
                self.report.outputs[step.id] = step.outputs[0]
            # a skipped step must nevertheless hand back what the following ones expect
            # from it: without that, registration would have no reference left on the
            # second run. The measurements are **re-judged** along the way: the cache
            # fingerprint deliberately ignores the approval criteria and the manual
            # rejections (see `SubframeSelector.cache_values`), so it is the current values
            # that must produce the weights, not those frozen in the file.
            if step.id.startswith("measure_"):
                self.measurements[step.group or step.id] = step.process.evaluate(
                    selection.read_measures(step.outputs[0]))
            self.monitor.report(offset + span, f"{step.label} (already up to date)")
            return

        # Window of the step: the runner pours its "frame i/N" into it, and an instrumented
        # global process finds it in thread-local storage — its 0→1 is exactly the duration
        # of the step. Per-frame steps subdivide further (see `_run_per_frame`).
        progress = ScaledMonitor(self.monitor, offset, span)
        self._run_hook(step, "before")
        with _sub_progress(self.monitor, offset, span):
            if step.kind == "per_frame":
                self._run_per_frame(step, progress)
            else:
                self._run_global(step, progress)
        # Before `write_manifest`: a hook that fails leaves the step unsealed, hence
        # replayed at the next run — rather than a cache asserting that the work is done.
        self._run_hook(step, "after")

        for output in step.outputs:
            cache.write_manifest(step, output, resolved)
        if step.outputs:
            self.report.outputs[step.id] = step.outputs[0]
        self.report.executed.append(step.id)

    # --- loop ------------------------------------------------------------------
    def run(self) -> RunReport:
        self.report.notes += list(self.plan.notes)
        total = sum(s.weight for s in self.plan.steps) or 1
        acquired = 0
        for step in self.plan.steps:
            self.monitor.checkpoint()
            span = step.weight / total
            self._run_step(step, acquired / total, span)
            acquired += step.weight
            # the measurements have just all been made: this is the moment to choose
            if step.id.startswith("measure_") and step is self._last_measure():
                self._choose_reference()
        self.monitor.report(1.0, "Pre-processing finished")
        self.report.measurements = self.measurements
        # The total integration time announced by the plan is an upper bound: a frame
        # rejected by the selector remains an input of the integration, it simply weighs
        # zero. Once the measurements are made, the real number can at last be given.
        self.report.products = selection.summary(self.plan, self.measurements)
        return self.report

    def _last_measure(self) -> PlanStep | None:
        measures = [s for s in self.plan.steps if s.id.startswith("measure_")]
        return measures[-1] if measures else None


def run(plan: Plan, on_progress: ProgressCallback | None = None, *,
        force: bool = False) -> RunReport:
    """Executes a plan and returns its report.

    ``on_progress(fraction, message)`` receives the global progress. If a monitor is already
    installed in the current thread (the case of a server job), it is reused — the
    cancellation triggered from the interface thus travels all the way here with no extra
    plumbing.

    >>> report = retina.pipeline.run(plan, on_progress=print)
    >>> report.results
    ['/data/M31/retina_pipeline/integrated/light_L_300s_bin1_m10C.fits']
    """
    monitor = context.get_monitor()
    if monitor is None:
        monitor = ProgressMonitor()
    if on_progress is not None:
        previous = monitor.on_progress

        def relay(fraction, message=""):
            if previous is not None:
                previous(fraction, message)
            on_progress(fraction, message)

        monitor.on_progress = relay
    try:
        return _Runner(plan, monitor, force).run()
    finally:
        if on_progress is not None:
            monitor.on_progress = previous
