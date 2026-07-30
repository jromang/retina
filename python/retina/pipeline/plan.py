"""The execution plan: what the pipeline is going to do, before it does it.

A :class:`Plan` is an ordered list of :class:`PlanStep`, each carrying **real process
instances** and the concrete paths of its inputs and outputs. It is therefore inspectable
(``plan.describe()``), editable (``plan.steps[3].process.sigma_high = 2.5``),
JSON-serializable, and exportable step by step as a :class:`ProcessContainer`.

# Why a separate object, and not a ProcessContainer

A ``ProcessContainer`` is a linear recipe applied to **one** view. A pre-processing run does
two things it cannot do: execute *global* processes (``Integration`` reads N files and
produces one) and *multiply* a single recipe over every frame of a group. The ``Plan``
orchestrates; the ``ProcessContainer`` remains the brick of every per-frame step, reused as
is. Nothing is reinvented, and a step exports as a classic recipe to be replayed by hand.

# Built by phases, not by group

Steps are produced phase by phase (all the master biases, then all the darks, then all the
calibrations…), and not group by group. This is not cosmetic: the alignment reference frame
must be **common to every filter**, failing which the L, R, G and B layers will not
superimpose at composition time. *All* the measurements must therefore be made before the
first registration. Established practice proceeds the same way.

# Late bindings

Two values cannot be known at planning time: which frame will serve as the reference, and
what weights will come out of the measurements. The steps concerned declare them in
``bindings`` (``{"reference_path": "@reference"}``) and the runner resolves them along the
way. The plan thus stays entirely serializable, and the user explicitly sees what will be
decided en route.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace

from ..i18n import translate as _t
from ..process.base import Process
from ..process.container import ProcessContainer
from ..process.registry import get
from .groups import FrameGroup, match_calibration
from .presets import Preset, resolve
from .scan import OUTPUT_DIR_NAME, Inventory

PLAN_VERSION = "1.0"

#: late binding token: the reference frame, common to every group
REFERENCE = "@reference"
#: late binding token: the group's weights, derived from the measurements
WEIGHTS = "@weights"

#: output subfolders (the usual convention, trimmed down)
MASTERS_DIR = "masters"
CALIBRATED_DIR = "calibrated"
REGISTERED_DIR = "registered"
INTEGRATED_DIR = "integrated"
MEASURES_DIR = "measures"
OVERSCAN_DIR = "overscan"

#: below this, sigma rejection has too few samples to estimate a robust dispersion
MIN_FRAMES_FOR_REJECTION = 3


def _rejection(count: int, kind: str = "light") -> str:
    """Rejection suited to the number of frames — see :func:`Integration.choose_rejection`.

    The plan freezes it rather than letting ``auto`` decide at run time: a plan must say
    exactly what it is going to do, and stay reproducible if it is replayed later.
    """
    from ..processes.integration import choose_rejection

    return choose_rejection(count, kind)


def _outputs(inputs: list[str], directory: str, suffix: str) -> list[str]:
    """Deterministic output paths — a necessary condition for caching and resuming."""
    used: set[str] = set()
    out: list[str] = []
    for path in inputs:
        stem = os.path.splitext(os.path.basename(path))[0]
        name = f"{stem}{suffix}.fits"
        n = 1
        while name in used:  # two source folders may carry the same file name
            n += 1
            name = f"{stem}{suffix}_{n}.fits"
        used.add(name)
        out.append(os.path.join(directory, name))
    return out


@dataclass
class PlanStep:
    """A step: a recipe applied to each frame, or a global process."""

    id: str
    kind: str  # "per_frame" | "global"
    label: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    group: str | None = None
    #: recipe applied to **each** input (``kind="per_frame"``)
    recipe: ProcessContainer | None = None
    #: global process reading all the inputs at once (``kind="global"``)
    process: Process | None = None
    #: parameters resolved at run time: ``{parameter id: token}``
    bindings: dict[str, str] = field(default_factory=dict)
    #: FITS keywords to stamp on the output. A master must describe itself: without
    #: ``FILTER``, ``EXPTIME``, ``GAIN`` or temperature, a later run that finds it again in
    #: a library would no longer know what it applies to.
    keywords: dict = field(default_factory=dict)
    #: estimated size of **one** output, in bytes (float32, geometry of the group). Used to
    #: announce the disk space needed before launching. Zero if the geometry is unknown.
    output_bytes: int = 0
    #: Python scripts run around the step: ``{"before"|"after": path}``. The equivalent of
    #: event scripts, entrusted to the ``Script`` process — hence a verified digest,
    #: cancellable and echoed, with no extension mechanism to invent.
    hooks: dict[str, str] = field(default_factory=dict)

    @property
    def processes(self) -> list[Process]:
        if self.recipe is not None:
            return list(self.recipe.processes)
        return [self.process] if self.process is not None else []

    @property
    def weight(self) -> int:
        """Relative cost of the step — used to apportion the progress bar."""
        return max(1, len(self.inputs))

    def container(self) -> ProcessContainer:
        """The step as a classic recipe, inspectable and replayable."""
        return self.recipe if self.recipe is not None else ProcessContainer(self.processes)

    def describe(self) -> str:
        text_value = " → ".join(p.process_id for p in self.processes) or "(nothing)"
        target = f"{len(self.inputs)} frame(s)" if self.kind == "per_frame" else "global"
        deferred = f" [{', '.join(self.bindings.values())}]" if self.bindings else ""
        return f"{self.id}: {text_value} · {target}{deferred}"

    def to_dict(self) -> dict:
        data = {
            "id": self.id, "kind": self.kind, "label": self.label, "group": self.group,
            "inputs": list(self.inputs), "outputs": list(self.outputs),
            "bindings": dict(self.bindings), "keywords": dict(self.keywords),
            "output_bytes": self.output_bytes,
            "processes": [p.to_dict() for p in self.processes],
        }
        # Written only if there are any: a plan saved before hooks existed reads back
        # unchanged, and existing cache manifests keep their fingerprint.
        if self.hooks:
            data["hooks"] = dict(self.hooks)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> PlanStep:
        processes = [Process.from_dict(d) for d in data.get("processes", [])]
        kind = data["kind"]
        return cls(
            id=data["id"], kind=kind, label=data.get("label", data["id"]),
            inputs=list(data.get("inputs", [])), outputs=list(data.get("outputs", [])),
            group=data.get("group"), bindings=dict(data.get("bindings", {})),
            keywords=dict(data.get("keywords", {})),
            output_bytes=int(data.get("output_bytes", 0)),
            hooks=dict(data.get("hooks", {})),
            recipe=ProcessContainer(processes) if kind == "per_frame" else None,
            process=processes[0] if kind == "global" and processes else None,
        )

    def __repr__(self) -> str:
        return f"PlanStep({self.id!r}, {self.kind}, {len(self.inputs)} inputs)"


@dataclass
class PlanProduct:
    """A final image announced by the plan, with what characterizes it.

    The plan already promises its ``results`` — paths. What one wants to read *before*
    launching three hours of computation is rather: how many subs, of what duration, under
    which filter. The **total integration time** is the number that says whether the night
    was worth it, and no other screen gives it.
    """

    key: str
    filter: str | None = None
    frames: int = 0
    exposure: float | None = None
    path: str = ""

    @property
    def integration(self) -> float | None:
        """Total integration time, in seconds."""
        return None if self.exposure is None else self.frames * self.exposure

    def to_dict(self) -> dict:
        return {"key": self.key, "filter": self.filter, "frames": self.frames,
                "exposure": self.exposure, "path": self.path,
                "integration": self.integration}

    @classmethod
    def from_dict(cls, data: dict) -> PlanProduct:
        return cls(key=data["key"], filter=data.get("filter"),
                   frames=int(data.get("frames", 0)), exposure=data.get("exposure"),
                   path=data.get("path", ""))


def _duration(seconds: float) -> str:
    """Readable duration — nobody reads "12,000 s"."""
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes = round(seconds / 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def _bytes(size: float) -> str:
    """Readable size, in decimal units — those of the disk manufacturers."""
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1000:
            return f"{size:.0f} {unit}" if unit == "B" or size >= 100 else f"{size:.1f} {unit}"
        size /= 1000
    return f"{size:.1f} TB"


def _free_bytes(path: str) -> int | None:
    """Free space where the plan will write — the folder does not exist yet, so we walk up."""
    import shutil

    current = os.path.abspath(path)
    while True:
        if os.path.isdir(current):
            try:
                return shutil.disk_usage(current).free
            except OSError:
                return None
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


@dataclass
class Plan:
    """The complete pre-processing run, ready to execute — and to read before launching."""

    root: str
    output_dir: str
    steps: list[PlanStep] = field(default_factory=list)
    preset: Preset = field(default_factory=Preset)
    #: decisions and anomalies to bring to the user's attention
    notes: list[str] = field(default_factory=list)
    #: the final images, described — see :class:`PlanProduct`
    products: list[PlanProduct] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self):
        return iter(self.steps)

    def step(self, step_id: str) -> PlanStep:
        found = next((s for s in self.steps if s.id == step_id), None)
        if found is None:
            raise KeyError(_t("Unknown step: {step_id!r}").format(step_id=step_id))
        return found

    def container_for(self, step_id: str) -> ProcessContainer:
        """Exports a step as a classic recipe (inspection, manual replay)."""
        return self.step(step_id).container()

    @property
    def results(self) -> list[str]:
        """The final images the plan promises to produce.

        Astrometric solving then cropping, when they take place, are the last hands laid on
        the image: that one is the result, not the integrated image with incomplete edges
        that preceded it.
        """
        for prefix in ("platesolve_", "autocrop_"):
            last = [s.outputs[0] for s in self.steps
                        if s.id.startswith(prefix) and s.outputs]
            if last:
                return last
        return [s.outputs[0] for s in self.steps
                if s.id.startswith("integrate_") and s.outputs]

    def disk_usage(self) -> dict:
        """What the plan is going to write, per folder, and how much free space is left.

        An **estimate**: sizes are deduced from the geometry of the groups and from the
        float32 we write, without accounting for cropping or compression. It does not need
        to be right to the megabyte — it has to say *before* launching that a ×2 drizzle on
        three hundred subs demands four hundred gigabytes we do not have.
        """
        steps: dict[str, int] = {}
        for step in self.steps:
            if not step.output_bytes:
                continue
            folder = os.path.basename(os.path.dirname(step.outputs[0])) if step.outputs else ""
            # per-group subfolders (calibrated/<key>) add up under their parent
            for known in (MASTERS_DIR, CALIBRATED_DIR, REGISTERED_DIR, INTEGRATED_DIR,
                          OVERSCAN_DIR):
                if f"{os.sep}{known}{os.sep}" in step.outputs[0] or folder == known:
                    folder = known
                    break
            steps[folder] = steps.get(folder, 0) + len(step.outputs) * step.output_bytes
        total = sum(steps.values())
        return {"stages": steps, "total_bytes": total,
                "free_bytes": _free_bytes(self.output_dir)}

    def describe(self) -> str:
        lines = [f'Plan "{self.preset.name}" — {len(self.steps)} steps',
                  f"  source : {self.root}",
                  f"  output : {self.output_dir}"]
        if self.notes:
            lines.append("  notes:")
            lines += [f"    · {n}" for n in self.notes]
        lines.append("  steps:")
        lines += [f"    {i + 1:2d}. {s.describe()}" for i, s in enumerate(self.steps)]
        if self.products:
            # "at most": the frame selector has not spoken yet, and a sub it will set aside
            # is already counted here. The run report will give the real number.
            lines.append("  expected results (at most, before selection):")
            for product in self.products:
                frame = ("" if product.integration is None
                        else f" — {product.frames} × {product.exposure:g} s = "
                             f"{_duration(product.integration)}")
                lines.append(f"    · {os.path.basename(product.path)}{frame}")
        elif self.results:
            lines.append("  expected results:")
            lines += [f"    · {os.path.basename(r)}" for r in self.results]
        disk = self.disk_usage()
        if disk["total_bytes"]:
            free = disk["free_bytes"]
            missing_value = (" — NOT ENOUGH"
                             if free is not None and disk["total_bytes"] > free else "")
            available = "" if free is None else f", {_bytes(free)} free{missing_value}"
            lines.append(f"  to write: {_bytes(disk['total_bytes'])}{available}")
        return "\n".join(lines)

    def to_python_source(self) -> str:
        """The equivalent console code — this is what the wizard echoes."""
        return (f"inventory = retina.pipeline.scan({self.root!r})\n"
                f"plan = retina.pipeline.plan(inventory, preset={self.preset.name!r})\n"
                f"retina.pipeline.run(plan)")

    def to_dict(self) -> dict:
        return {
            "version": PLAN_VERSION, "root": self.root, "output_dir": self.output_dir,
            "preset": self.preset.to_dict(), "notes": list(self.notes),
            "products": [p.to_dict() for p in self.products],
            "disk": self.disk_usage(),
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Plan:
        version = data.get("version", PLAN_VERSION)
        if version.split(".")[0] != PLAN_VERSION.split(".")[0]:
            raise ValueError(_t("Plan version {version}, incompatible with {expected}").format(
                version=version, expected=PLAN_VERSION))
        return cls(
            root=data["root"], output_dir=data["output_dir"],
            preset=Preset.from_dict(data.get("preset", {})),
            notes=list(data.get("notes", [])),
            products=[PlanProduct.from_dict(p) for p in data.get("products", [])],
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> Plan:
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def __repr__(self) -> str:
        return f"Plan({self.preset.name!r}, {len(self.steps)} steps → {self.output_dir!r})"


class _Builder:
    """Assembles the plan phase by phase. Purely internal to :func:`plan`."""

    def __init__(self, inventory: Inventory, groups: list[FrameGroup], preset: Preset,
                 output_dir: str) -> None:
        self.inventory = inventory
        self.groups = groups
        self.preset = preset
        self.out = output_dir
        self.steps: list[PlanStep] = []
        self.notes: list[str] = []
        self.matches = match_calibration(groups)
        #: effective master of each calibration group, once its steps are laid down
        self.masters: dict[str, str] = {}
        #: current outputs of each group of lights, as the phases go by
        self.current: dict[str, list[str]] = {}
        #: outputs of registration alone, before normalization — source of the coverage
        self.registered: dict[str, list[str]] = {}
        #: input frames of each group, possibly overscan-corrected
        self.sources: dict[str, list[str]] = {}

    # --- helpers ---------------------------------------------------------------
    def _master_path(self, key: str, suffix: str = "") -> str:
        return os.path.join(self.out, MASTERS_DIR, f"master_{key}{suffix}.fits")

    def _add(self, step: PlanStep) -> PlanStep:
        self.steps.append(step)
        return step

    @staticmethod
    def _master_keywords(group: FrameGroup) -> dict:
        """What a master must say about itself in order to be found again later."""
        keywords: dict = {
            "IMAGETYP": f"Master {group.kind.capitalize()}",
            "XBINNING": group.binning,
            "YBINNING": group.binning,
        }
        if group.filter:
            keywords["FILTER"] = group.filter
        if group.exposure is not None:
            keywords["EXPTIME"] = group.exposure
        if group.gain is not None:
            keywords["GAIN"] = group.gain
        if group.temperature is not None:
            keywords["SET-TEMP"] = group.temperature
        keywords.update(group.extra)
        return keywords

    def _integrate(self, step_id: str, label: str, frames: list[str], output: str,
                   group: str | None = None, kind: str = "light",
                   keywords: dict | None = None, **kwargs) -> PlanStep:
        process = get("Integration")(frames=frames,
                                     rejection=_rejection(len(frames), kind),
                                     new_image_id=os.path.splitext(
                                         os.path.basename(output))[0], **kwargs)
        return self._add(PlanStep(id=step_id, kind="global", label=label, group=group,
                                  inputs=list(frames), outputs=[output], process=process,
                                  keywords=dict(keywords or {})))

    def _per_frame(self, step_id: str, label: str, recipe: ProcessContainer,
                   inputs: list[str], directory: str, suffix: str,
                   group: str | None = None, bindings: dict | None = None,
                   keywords: dict | None = None) -> PlanStep:
        outputs = _outputs(inputs, directory, suffix)
        return self._add(PlanStep(id=step_id, kind="per_frame", label=label, group=group,
                                  inputs=list(inputs), outputs=outputs, recipe=recipe,
                                  bindings=dict(bindings or {}),
                                  keywords=dict(keywords or {})))

    def _of_kind(self, kind: str) -> list[FrameGroup]:
        return [g for g in self.groups if g.kind == kind]

    def _sources(self, group: FrameGroup) -> list[str]:
        """Input frames of the group: overscan-corrected if that step took place."""
        return self.sources.get(group.key, group.paths)

    # --- phases ----------------------------------------------------------------
    def _reuse_master(self, group: FrameGroup) -> bool:
        """Records a master supplied with the batch and removes the need to build one.

        That is the point of a master library: thirty 300 s darks are slow to stack and do
        not change from one session to the next. The run cache is not enough here — it
        knows only *our* outputs, not the files the user brings along.
        """
        existing = group.master
        if existing is None:
            return False
        self.masters[group.key] = existing
        self.notes.append(
            _t("{key}: reusing supplied master ({file})").format(
                key=group.key, file=os.path.basename(existing)))
        return True

    def overscan(self) -> None:
        """Corrects the bias drift and removes the unexposed area — before everything else.

        Before, because the overscan measures the bias of *this* sub: subtracting it after a
        master bias would amount to correcting twice. And on **every** kind of frame,
        failing which the geometries would stop agreeing — a cropped master would not apply
        to a light that is not.
        """
        if not self.preset.overscan:
            return
        for group in self.groups:
            if group.master is not None:
                continue  # a supplied master was already corrected by whoever built it
            biassec, trimsec = group.sections
            if not biassec and not trimsec:
                continue
            recipe = ProcessContainer().add(get("Overscan")(
                bias_section=biassec or "", trim_section=trimsec or ""))
            step = self._per_frame(
                f"overscan_{group.key}", _t("Overscan — {key}").format(key=group.key), recipe,
                group.paths, os.path.join(self.out, OVERSCAN_DIR, group.key), "_o",
                group=group.key)
            self.sources[group.key] = step.outputs
            self.notes.append(
                _t("{key}: overscan {biassec} corrected, useful area {trimsec}").format(
                    key=group.key,
                    biassec=biassec or "—",
                    trimsec=trimsec or _t("unchanged")))

    def masters_bias(self) -> None:
        for group in self._of_kind("bias"):
            if self._reuse_master(group):
                continue
            output = self._master_path(group.key)
            self._integrate(f"master_{group.key}", _t("Master bias — {key}").format(key=group.key),
                            self._sources(group), output, group=group.key, kind="master",
                            keywords=self._master_keywords(group))
            self.masters[group.key] = output
            if self.preset.superbias:  # applies only to the master we have just built
                affine = self._master_path(group.key, "_superbias")
                recipe = ProcessContainer().add(get("Superbias")())
                step = self._per_frame(f"superbias_{group.key}",
                                       f"Superbias — {group.key}", recipe, [output],
                                       os.path.join(self.out, MASTERS_DIR), "_superbias",
                                       group=group.key)
                step.outputs = [affine]
                self.masters[group.key] = affine

    def masters_dark(self) -> None:
        for group in self._of_kind("dark"):
            if self._reuse_master(group):
                continue
            output = self._master_path(group.key)
            self._integrate(f"master_{group.key}", _t("Master dark — {key}").format(key=group.key),
                            self._sources(group), output, group=group.key, kind="master",
                            keywords=self._master_keywords(group))
            self.masters[group.key] = output

    def darks_current(self) -> None:
        """Dark current = master dark − master bias, required by scaling."""
        seen: set[tuple[str, str]] = set()
        for match in self.matches.values():
            if not match.scaled or match.dark is None or match.bias is None:
                continue
            pair = (match.dark.key, match.bias.key)
            if pair in seen:
                continue
            seen.add(pair)
            recipe = ProcessContainer().add(get("ImageCalibration")(
                master_bias=self.masters[match.bias.key], pedestal_mode="none"))
            step = self._per_frame(
                f"darkcurrent_{match.dark.key}", f"Dark current — {match.dark.key}",
                recipe, [self.masters[match.dark.key]],
                os.path.join(self.out, MASTERS_DIR), "_current", group=match.dark.key)
            self.masters[f"{match.dark.key}@current"] = step.outputs[0]

    def masters_flat(self) -> None:
        for group in self._of_kind("flat"):
            if self._reuse_master(group):
                continue  # a master flat is already calibrated: do not recalibrate it
            match = self.matches.get(group.key)
            frames = self._sources(group)
            if match is not None and not match.is_empty:
                # a flat is always positive: no pedestal to add to it
                recipe = ProcessContainer().add(get("ImageCalibration")(
                    master_bias=self.masters.get(match.bias.key, "") if match.bias else "",
                    master_dark=self.masters.get(match.dark.key, "") if match.dark else "",
                    pedestal_mode="none"))
                step = self._per_frame(
                    f"calibrate_{group.key}", _t("Flat calibration — {key}").format(key=group.key),
                    recipe, frames, os.path.join(self.out, CALIBRATED_DIR, group.key),
                    "_c", group=group.key)
                frames = step.outputs
            output = self._master_path(group.key)
            self._integrate(f"master_{group.key}", _t("Master flat — {key}").format(key=group.key),
                            frames, output, group=group.key, kind="master",
                            keywords=self._master_keywords(group))
            self.masters[group.key] = output

    def calibrate_lights(self) -> None:
        pattern = self.inventory.bayer_pattern or "RGGB"
        debayer = (self.preset.debayer if self.preset.debayer is not None
                   else self.inventory.is_osc)
        # Dual-band only makes sense on a matrixed sensor: without a Bayer matrix, there are
        # no red and green sites to separate.
        dual_band = bool(self.preset.dual_band and (debayer or self.inventory.bayer_pattern))
        derived: list[FrameGroup] = []
        for group in self._of_kind("light"):
            match = self.matches[group.key]
            self.notes += [f"{group.key} : {n}" for n in match.notes]
            recipe = ProcessContainer()
            if match.is_empty:
                self.notes.append(
                    _t("{key}: no calibration master, lights used raw").format(key=group.key))
            else:
                dark = ""
                if match.dark is not None:
                    key = f"{match.dark.key}@current" if match.scaled else match.dark.key
                    dark = self.masters.get(key, "")
                # Optimization only makes sense on a dark current that is being scaled: on a
                # dark of the right exposure, there is nothing to search for.
                optimize = self.preset.dark_optimization and match.scaled
                recipe.add(get("ImageCalibration")(
                    master_bias=self.masters.get(match.bias.key, "") if match.bias else "",
                    master_dark=dark,
                    master_flat=self.masters.get(match.flat.key, "") if match.flat else "",
                    dark_scale=match.dark_scale,
                    dark_optimize=optimize,
                    # The pedestal protects the negative values that subtracting the dark
                    # may produce; clipping to zero would turn them into a silent bias on
                    # the background. Established practice sets it the same way, per group
                    # of lights, and then adjusts it step by step (here:
                    # `pipeline.set_step_params`).
                    pedestal_mode=self.preset.pedestal_mode,
                    pedestal=self.preset.pedestal))
                if optimize:
                    self.notes.append(
                        _t("{key}: dark scale searched around ×{scale:.2f}").format(
                            key=group.key, scale=match.dark_scale))
            if self.preset.cosmetic:
                recipe.add(get("CosmeticCorrection")(hot_sigma=self.preset.hot_sigma,
                                                     cold_sigma=self.preset.cold_sigma))
            # LPS **before** the debayer, as is usual: afterwards, interpolation has mixed
            # the pattern between colors and it is no longer separable. The `cfa` flag
            # therefore follows exactly the presence of a debayer to come — as long as it
            # has not taken place, every other column sees a different filter and the
            # sub-planes have to be treated separately.
            if self.preset.lps:
                recipe.add(get("LinearPatternSubtraction")(
                    columns=self.preset.lps_columns, rows=self.preset.lps_rows,
                    mode="auto", cfa=bool(debayer)))
            # Dual-band: no debayering. Interpolating would mix Hα (red) and OIII (green)
            # on every pixel, and the two lines would no longer be separable. Superpixel
            # extraction comes right after, as a distinct step.
            if debayer and not dual_band:
                recipe.add(get("Debayer")(pattern=pattern))

            if len(recipe):
                step = self._per_frame(
                    f"calibrate_{group.key}", _t("Calibration — {key}").format(
                        key=group.key), recipe,
                    self._sources(group),
                    os.path.join(self.out, CALIBRATED_DIR, group.key), "_c",
                    group=group.key)
                self.current[group.key] = step.outputs
            else:
                self.current[group.key] = self._sources(group)
            if dual_band:
                derived += self._extract_dual_band(group, pattern)

        # The substitution is made **after** the loop: `self.groups` is what `_of_kind`
        # walks, and mutating it mid-iteration would have the derived groups treated as
        # groups to calibrate. `self.matches` is no longer consulted beyond this phase.
        if derived:
            self.groups = [g for g in self.groups if g.kind != "light"] + derived

    def _extract_dual_band(self, group: FrameGroup, pattern: str) -> list[FrameGroup]:
        """Splits a dual-band OSC group into its two bands. Returns the derived groups.

        The gesture is that of a color sensor behind an Hα/OIII filter: the Bayer matrix
        serves as a spectral separator instead of serving to make color. Each band becomes a
        group of lights in its own right, and all the following phases (measurement,
        registration, normalization, integration) apply without knowing anything about the
        matter — hence two integrated images, one per line, correctly labelled `FILTER`.
        """
        derived: list[FrameGroup] = []
        for band, name in (("ha", "Ha"), ("oiii", "OIII")):
            derive = replace(group, filter=name)
            recipe = ProcessContainer()
            recipe.add(get("ExtractDualBand")(pattern=pattern, band=band))
            step = self._per_frame(
                f"extract_{derive.key}",
                _t("{band} extraction — {key}").format(band=name, key=group.key),
                recipe, self.current[group.key],
                os.path.join(self.out, CALIBRATED_DIR, derive.key), f"_{band}",
                group=derive.key, keywords={"FILTER": name})
            self.current[derive.key] = step.outputs
            derived.append(derive)
        self.notes.append(
            _t("{key}: dual-band OSC, Ha and OIII extracted separately (no debayer)").format(
                key=group.key))
        return derived

    def measure(self) -> None:
        """Measurements of **all** the groups before any registration — cf. module header."""
        if not self.preset.measure:
            return
        for group in self._of_kind("light"):
            frames = self.current[group.key]
            # measurements have an output (the measurement JSON) so as to be cacheable:
            # detecting the stars of a hundred frames is the dominant cost of a second run
            output = os.path.join(self.out, MEASURES_DIR, f"{group.key}.json")
            self._add(PlanStep(id=f"measure_{group.key}", kind="global",
                               label=_t("Measurements — {key}").format(
                                   key=group.key), group=group.key,
                               inputs=list(frames), outputs=[output],
                               process=get("SubframeSelector")(
                                   frames=frames,
                                   approval=self.preset.approval,
                                   weighting=self.preset.weighting_expression,
                                   min_weight=self.preset.min_weight)))

    def register(self) -> None:
        """Registration then normalization, in **two** distinct steps.

        Chaining them in a single recipe would be one line shorter and wrong in two ways.
        First because normalization erases the zero fill that registration leaves on the
        edges: that fill is precisely what says which part of the image was seen by every
        sub, and the final crop depends on it. Second because two steps are cached
        separately — changing the normalization scale then does not re-run the star
        matching, which is by far the more expensive of the two.
        """
        if not self.preset.register or self.preset.drizzle:
            return
        for group in self._of_kind("light"):
            aligned = self._per_frame(
                f"register_{group.key}", _t("Registration — {key}").format(key=group.key),
                ProcessContainer().add(get("StarAlignment")()),
                self.current[group.key],
                os.path.join(self.out, REGISTERED_DIR, group.key), "_r",
                group=group.key, bindings={"reference_path": REFERENCE})
            self.current[group.key] = aligned.outputs
            #: outputs of registration alone: their zero fill measures the coverage
            self.registered[group.key] = aligned.outputs

    def normalize(self) -> None:
        """A phase distinct from registration — cf. :meth:`register`."""
        if not self.preset.register or self.preset.drizzle or not self.preset.normalize:
            return
        for group in self._of_kind("light"):
            step = self._per_frame(
                f"normalize_{group.key}", _t("Normalization — {key}").format(key=group.key),
                ProcessContainer().add(get("LocalNormalization")(
                    scale=self.preset.normalization_scale)),
                self.current[group.key],
                os.path.join(self.out, REGISTERED_DIR, group.key), "_n",
                group=group.key, bindings={"reference_path": REFERENCE})
            self.current[group.key] = step.outputs

    def integrate(self) -> None:
        weighted = self.preset.weighting and self.preset.measure
        for group in self._of_kind("light"):
            frames = self.current[group.key]
            output = os.path.join(self.out, INTEGRATED_DIR, f"{group.key}.fits")
            if self.preset.drizzle:
                # Drizzle receives the **calibrated** frames, not the registered ones: the
                # registration interpolation would already have mixed the sub-pixels it has
                # to reconstruct.
                process = get("DrizzleIntegration")(
                    frames=frames, scale=self.preset.drizzle_scale,
                    pixfrac=self.preset.drizzle_pixfrac,
                    new_image_id=group.key)
                step = self._add(PlanStep(
                    id=f"integrate_{group.key}", kind="global",
                    label=_t("Drizzle — {key}").format(key=group.key), group=group.key,
                    inputs=list(frames), outputs=[output], process=process,
                    bindings={"reference_path": REFERENCE}))
                continue
            step = self._integrate(
                f"integrate_{group.key}", _t("Integration — {key}").format(
                    key=group.key), frames, output,
                group=group.key, sigma_low=self.preset.sigma_low,
                sigma_high=self.preset.sigma_high)
            if weighted:
                step.bindings["weights"] = WEIGHTS

    def autocrop(self) -> None:
        """Crops the incomplete edges of the integrated images — last step, as is usual."""
        if not self.preset.autocrop:
            return
        for group in self._of_kind("light"):
            entry = os.path.join(self.out, INTEGRATED_DIR, f"{group.key}.fits")
            # the frames that went into the integration: it is on them that the real
            # coverage is measured, the integrated image having already averaged the
            # partial edges
            coverage = self.registered.get(group.key) or self.current[group.key]
            recipe = ProcessContainer().add(get("AutoCrop")(frames=list(coverage)))
            step = self._per_frame(
                f"autocrop_{group.key}", _t("Crop — {key}").format(key=group.key), recipe, [entry],
                os.path.join(self.out, INTEGRATED_DIR), "_crop", group=group.key)
            self.current[group.key] = step.outputs

    def platesolve(self) -> None:
        """Solves the final images — last phase, after cropping.

        After, and not before: cropping moves the origin, which would invalidate an already
        computed WCS. Solving the image as it is delivered is the only way to obtain
        astrometry that matches it.
        """
        # A mosaic **requires** astrometry: it is what places the panels relative to one
        # another. Plate-solving stays disabled by default elsewhere (it downloads its
        # indexes on first call, which we do not trigger behind the user's back) — but here,
        # refusing it would amount to announcing a mosaic we would not know how to assemble.
        # The plan says so in its notes.
        if not self.preset.platesolve and not self._panels():
            return
        if not self.preset.platesolve:
            self.notes.append(
                _t("mosaic detected: astrometry enabled (index files downloaded on first "
                   "use, cached afterwards)"))
        for group in self._of_kind("light"):
            entry = self.current[group.key]
            if not entry:
                continue
            output = os.path.join(self.out, INTEGRATED_DIR, f"{group.key}_wcs.fits")
            self._add(PlanStep(
                id=f"platesolve_{group.key}", kind="global",
                label=_t("Astrometry — {key}").format(key=group.key), group=group.key,
                inputs=list(entry), outputs=[output],
                process=get("PlateSolve")()))
            self.current[group.key] = [output]

    def _panels(self) -> dict[int, list[FrameGroup]]:
        """Groups of lights by panel number — empty if there is no mosaic."""
        panels: dict[int, list[FrameGroup]] = {}
        for group in self._of_kind("light"):
            if group.panel:
                panels.setdefault(group.panel, []).append(group)
        return panels

    def mosaic(self) -> None:
        """Assembles the panels of a mosaic, filter by filter.

        The grouping is done **by filter and not by panel**: an LRGB mosaic of four panels
        gives four assemblies (one per layer), not a mixture of the layers. Each panel was
        integrated separately, with its own registration reference (two disjoint panels have
        no stars in common to match), then solved; `MosaicReproject` computes the common
        grid from their WCS.
        """
        panels = self._panels()
        if len(panels) < 2:
            return
        by_filter: dict[str, list[FrameGroup]] = {}
        for groups in panels.values():
            for group in groups:
                by_filter.setdefault(group.filter or "", []).append(group)

        for filter, groups in sorted(by_filter.items()):
            entries = [path for g in sorted(groups, key=lambda g: g.panel)
                       for path in self.current[g.key]]
            if len(entries) < 2:
                continue
            name = f"mosaic_{filter}" if filter else "mosaic"
            output = os.path.join(self.out, INTEGRATED_DIR, f"{name}.fits")
            self._add(PlanStep(
                id=name, kind="global",
                label=_t("Mosaic — {n} panels{filter}").format(
                    n=len(entries), filter=f" ({filter})" if filter else ""),
                inputs=list(entries), outputs=[output],
                process=get("MosaicReproject")(frames=entries, new_image_id=name)))
        self.notes.append(
            _t("{n} mosaic panels detected: each is integrated on its own, then assembled "
               "on a common WCS grid").format(n=len(panels)))

    def check(self) -> None:
        """Anomalies better seen before three hours of computation than after."""
        if self.preset.drizzle and not self.preset.measure:
            self.notes.append(
                _t("drizzle without measurements: no reference to aim at, frames will be "
                  "assumed already aligned"))
        lights = self._of_kind("light")
        if not lights:
            self.notes.append(_t("no light: nothing to integrate"))
        expected_items = self.preset.expected_filters
        if expected_items:
            presents = {(g.filter or "").lower() for g in lights}
            manquants = [f for f in expected_items if f.lower() not in presents]
            if manquants:
                self.notes.append(
                    _t("filters expected by the preset but missing: {filters}").format(
                        filters=", ".join(manquants)))
        for group in lights:
            if len(group) < MIN_FRAMES_FOR_REJECTION:
                self.notes.append(
                    _t("{key}: {count} frame(s), too few for robust rejection").format(
                        key=group.key, count=len(group)))

    def _final_output(self, key: str) -> str | None:
        """The last hand laid on a group's image — same rule as ``Plan.results``."""
        for prefix in ("platesolve_", "autocrop_", "integrate_"):
            step = next((s for s in self.steps
                         if s.id == f"{prefix}{key}" and s.outputs), None)
            if step is not None:
                return step.outputs[0]
        return None

    def products(self) -> list[PlanProduct]:
        """Describes what the plan will return, group of lights by group of lights."""
        products = []
        for group in self._of_kind("light"):
            path = self._final_output(group.key)
            if path is None:
                continue
            # the count that enters the integration, and not that of the group — a frame
            # that calibration will lose is no longer there. It is an **upper bound**: the
            # plan is built before any measurement, and a frame the selector will reject
            # stays an input (it weighs zero). The exact number comes from the run report,
            # via `selection.summary`.
            step = next((s for s in self.steps if s.id == f"integrate_{group.key}"), None)
            products.append(PlanProduct(
                key=group.key, filter=group.filter,
                frames=len(step.inputs) if step else len(group),
                exposure=group.exposure, path=path))
        return products

    def sizes(self) -> None:
        """Estimates the size of one output of each step, to announce the disk cost.

        Debayering triples the weight, drizzle multiplies it by the square of its factor:
        these are exactly the two settings that overflow a disk, hence the two that have to
        be counted.
        """
        geometry = {g.key: (g.width, g.height) for g in self.groups}
        channels = dict.fromkeys(geometry, 1)
        scales = dict.fromkeys(geometry, 1.0)
        for step in self.steps:
            if step.group is None or not step.outputs:
                continue
            # the measurement phase writes a JSON, not an image: counting it as a whole
            # frame would inflate the estimate by one sub per group of lights
            if not step.outputs[0].lower().endswith(".fits"):
                continue
            if any(p.process_id == "Debayer" for p in step.processes):
                channels[step.group] = 3
            drizzle = next((float(p.scale) for p in step.processes
                            if p.process_id == "DrizzleIntegration"), None)
            if drizzle is not None:
                # and everything that follows inherits the enlargement, not just the drizzle
                scales[step.group] = drizzle
            width, height = geometry.get(step.group, (None, None))
            if not width or not height:
                continue
            scale = scales.get(step.group, 1.0)
            step.output_bytes = int(width * scale * height * scale
                                    * channels.get(step.group, 1) * 4)

    def build(self) -> Plan:
        self.overscan()
        self.masters_bias()
        self.masters_dark()
        self.darks_current()
        self.masters_flat()
        self.calibrate_lights()
        self.measure()
        self.register()
        self.normalize()
        self.integrate()
        self.autocrop()
        self.platesolve()
        self.mosaic()
        self.check()
        self.sizes()
        return Plan(root=self.inventory.root, output_dir=self.out, steps=self.steps,
                    preset=self.preset, notes=self.notes, products=self.products())


def _default_output_dir(root: str) -> str:
    """Where to write, absent an explicit indication.

    Without a preference, next to the raw frames — the original behavior. With one, in a
    **subfolder named after the root**: a shared, bare output folder would make two targets
    processed on the same day collide, and the user would only see overwritten files.
    """
    from ..preferences import value

    chosen = str(value("folders.pipeline_output_dir") or "").strip()
    if not chosen:
        return os.path.join(root, OUTPUT_DIR_NAME)
    return os.path.join(chosen, os.path.basename(os.path.normpath(root)))


def plan(inventory: Inventory, preset: str | Preset | dict | None = "auto", *,
         output_dir: str | None = None,
         groups: list[FrameGroup] | None = None) -> Plan:
    """Builds the execution plan of an inventory.

    ``groups`` allows passing a hand-corrected grouping (the wizard lets the user reclassify
    a badly detected frame before planning).

    >>> inventory = retina.pipeline.scan("/data/M31")
    >>> plan = retina.pipeline.plan(inventory, preset="auto")
    >>> print(plan.describe())
    """
    settings = resolve(preset)
    batches = groups if groups is not None else inventory.groups(**settings.tolerances())
    output = output_dir or _default_output_dir(inventory.root)
    return _Builder(inventory, batches, settings, os.path.abspath(output)).build()
