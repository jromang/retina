"""Local AI processes — denoising and deconvolution by neural network.

The engine is :mod:`retina.ai`: cached ONNX session, blended tiling, progress and cancellation
per tile. These two processes are nothing but its parameter table.

# Traceability, which is the real subject

What distinguishes Retina from a photo-retouching program is that every gesture is a
replayable ``ProcessInstance``. A neural network is no exception: the model used goes into the
history, into the Python echo, into the recipe, into the ``.retina`` project and into the FITS
keywords of the saved image. This is the concrete answer to the charge of hallucination made
against these tools — not "trust us", but *here is exactly which file, of which fingerprint,
produced these pixels*.

The mechanism is deliberately as dumb as it can be: ``model_sha256`` and ``model_version`` are
**parameters** that ``_apply`` fills in. They therefore inherit all the existing
serialization, without any format having to change. On replay, a fingerprint that no longer
matches interrupts nothing — it **warns**: the result will be different, and the user has to
know it rather than discover it.

# Why no model is offered by default

Three sources, in the order in which :func:`~retina.ai.models.ensure` prefers them: a model
**discovered** in a local GraXpert installation (used in place), an entry of the **manifest**
(GraXpert models re-hosted on Hugging Face, downloaded on demand), or a direct **path** through
``model``. See :mod:`retina.ai.models`.

One point the user cannot guess, and which must therefore be spelled out: the **GraXpert**
models are under CC BY-NC-SA 4.0 — free, but **commercial use is forbidden**, whereas Retina
itself restricts nothing. The "Licenses" panel (:mod:`retina.credits`) mentions it, and the
restriction follows the model all the way into the FITS keywords.
"""

from __future__ import annotations

import numpy as np

#: value of ``model_id`` meaning "the most recent one for the task". Re-exported for the docs
#: and for the neighboring processes; the definition lives in :mod:`retina.ai.models`.
from ..ai.models import LATEST
from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def model_selector_params(
    visible_when: tuple[str, tuple[object, ...]] | None = None,
) -> list[Parameter]:
    """The model selection parameters, common to every AI process (denoising, deconvolution,
    background removal). A single definition, so that the selector behaves the same way
    everywhere.

    ``model_id`` is an ``enum`` with no static choices: the menu is filled on the fly by
    ``parameter_choices``, reflecting the live catalog (manifest + local GraXpert install).
    ``latest`` by default → the process picks the most recent one by itself.

    ``visible_when`` gates the whole block: ``BackgroundExtraction`` only shows it under its
    ``ai`` backend, where ``AIDenoise`` (pure AI) leaves it visible at all times.
    """
    return [
        Parameter("model_id", "enum", LATEST, label=N_("Model"), visible_when=visible_when),
        Parameter("model", "path", "", label=N_("Local model (.onnx), overrides the above"),
                  visible_when=visible_when),
        # Filled in at run time: they trace the model actually used. Leaving them empty at
        # construction time is normal.
        Parameter("model_version", "str", "", label=N_("Model version (recorded)"),
                  visible_when=visible_when),
        Parameter("model_sha256", "str", "", label=N_("Model fingerprint (recorded)"),
                  visible_when=visible_when),
    ]


class ModelTracing:
    """Mixin: model resolution, traceability, FITS keywords.

    Shared by the processes that use a model from the catalog — ``_AIProcess`` (denoising,
    deconvolution) and ``BackgroundExtraction``. The mixin does not know *how* the model is
    run (tiled, full frame…); it merely answers "which file, and leave a trace of it".

    The host supplies ``catalog_tasks`` (the tasks whose models the menu lists) and a
    property/attribute ``task`` (that of the model to resolve — which may depend on a
    parameter).
    """

    catalog_tasks: tuple[str, ...] = ()

    @classmethod
    def parameter_choices(cls, param_id: str) -> tuple[str, ...] | None:
        if param_id != "model_id":
            return None
        from ..ai import models

        return models.choices_for_tasks(cls.catalog_tasks)

    def _resolve_model(self) -> tuple[str, str, str]:
        from ..ai import models

        return models.resolve(str(self.model_id), str(self.model), self.task)

    def _trace_model(self, path: str, name: str, version: str) -> None:
        """Records the model identity in the instance — hence in all that serializes it."""
        from ..ai.models import sha256_of

        digest = sha256_of(path)
        if self.model_sha256 and self.model_sha256 != digest:
            self._warn_fingerprint()
        self.model_sha256 = digest
        self.model_version = version
        self._identity = (name, version, digest)

    def _warn_fingerprint(self) -> None:
        from ..process import context

        message = _t("{process}: the model fingerprint differs from the recorded one — "
                     "the result will not be identical.").format(process=self.process_id)
        try:
            app = context.get_application()
            if app is not None:
                app.notify(message, kind="warning", source="retina.ai")
        except Exception:  # headless, no application: the message has nobody to go to
            pass

    def _write_model_keywords(self, view) -> None:
        """Name, version and fingerprint of the model in the window's keywords.

        Accepted limitation, the same as ``FITSHeader``: ``execute_on_image`` has no window,
        hence no keywords. Traceability there goes through the instance, which is enough to
        replay.
        """
        identite = getattr(self, "_identity", None)
        if identite and view.window is not None:
            name, version, digest = identite
            view.window.keywords["AIMODEL"] = (name, "AI model used by Retina")
            if version:
                view.window.keywords["AIMODVER"] = (version, "AI model version")
            view.window.keywords["AIMODSHA"] = (digest[:16], "AI model SHA-256 (truncated)")


class _AIProcess(ModelTracing, Process):
    """Base of the **tiled** AI processes (denoising, deconvolution): model resolution,
    execution by blended tiles, traceability."""

    #: task of the model to resolve. For a process where it depends on a parameter
    #: (``AIDeconvolution``), it is a **property**; ``catalog_tasks`` (mixin) gives the
    #: class-level view the drop-down menu needs, without an instance.
    task: str = ""
    #: prefix of the progress messages, already translated at call time
    progress_label: str = N_("AI model")
    supports_realtime = False  # one inference per tile, even for a reduced preview

    #: common parameters, taken as they are by the subclasses
    base_parameters = [
        *model_selector_params(),
        Parameter("strength", "real", 1.0, 0.0, 1.0, label=N_("Strength")),
        Parameter("tile_size", "int", 256, 32, 2048, label=N_("Tile size")),
        Parameter("overlap", "int", 32, 0, 512, label=N_("Overlap (px)")),
    ]

    # --- execution ------------------------------------------------------------
    def _infer(self, data: np.ndarray, extra: dict | None = None) -> np.ndarray:
        from ..ai.onnx import open_session, run_tiled

        path, name, version = self._resolve_model()
        self._trace_model(path, name, version)
        label_text = _t(self.progress_label)

        def advance(fraction: float, done: int, total: int) -> None:
            self._progress(fraction, _t("{label} — tile {n}/{total}").format(
                label=label_text, n=done, total=total))

        return run_tiled(data, open_session(path), tile_size=int(self.tile_size),
                         overlap=int(self.overlap), extra_inputs=extra, progress=advance)

    def _melanger(self, entry: np.ndarray, output: np.ndarray) -> np.ndarray:
        """Doses the effect. At 1 the network decides alone; below, part of the original stays."""
        force = float(np.clip(self.strength, 0.0, 1.0))
        if force >= 1.0:
            return output.astype(np.float32)
        return (entry * (1.0 - force) + output * force).astype(np.float32)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        return self._melanger(data, self._infer(data))

    def execute_on(self, view) -> bool:
        """As the base class, plus the model identity in the window's keywords."""
        self._identity: tuple[str, str, str] | None = None
        result = super().execute_on(view)
        if result:
            self._write_model_keywords(view)
        return result


@register
class AIDenoise(_AIProcess):
    """Denoising by neural network (local ONNX model)."""

    process_id = "AIDenoise"
    category = "NoiseReduction"
    task = "denoise"
    catalog_tasks = ("denoise",)
    progress_label = N_("AI denoise")
    parameters = list(_AIProcess.base_parameters)


@register
class AIDeconvolution(_AIProcess):
    """Deconvolution by neural network — extended object or stars (local ONNX model)."""

    process_id = "AIDeconvolution"
    category = "Deconvolution"
    catalog_tasks = ("deconv_object", "deconv_stellar")
    progress_label = N_("AI deconvolution")
    parameters = [
        Parameter("target", "enum", "object", choices=("object", "stellar"),
                  label=N_("Target")),
        *_AIProcess.base_parameters,
    ]

    @property
    def task(self) -> str:  # type: ignore[override]
        return "deconv_stellar" if self.target == "stellar" else "deconv_object"
