"""Background & gradient: background extraction (≈ DBE/ABE) and neutralization (photutils)."""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register
from .ai import ModelTracing, model_selector_params

#: mirror border added before the AI inference (GraXpert convention: 240 useful + 8 on each side
#: = 256, the network's input size). Removing that border afterwards avoids the edge artifact.
_BGE_PAD = 8
_BGE_SIZE = 256


@register
class BackgroundExtraction(ModelTracing, Process):
    """Estimates and subtracts the background/gradient — robust 2D model (photutils) or a
    neural network (GraXpert).

    Two engines, a single output contract (``subtract`` removes the background, otherwise it is
    returned). The ``ai`` backend follows GraXpert's recipe for its BGE model: since the
    background is smooth by assumption, **the whole** image is reduced to 256×256, estimated
    there in a single inference, then upscaled again — no need to tile as for denoising.
    Traceability (name, version, model fingerprint in the history and in the FITS keywords)
    comes from the mixin, shared by the AI processes.
    """

    process_id = "BackgroundExtraction"
    category = "BackgroundModelization"
    task = "background"
    catalog_tasks = ("background",)
    parameters = [
        Parameter("backend", "enum", "photutils",
                  choices=("photutils", "ai"), label=N_("Engine")),
        Parameter("box_size", "int", 64, 4, 1024, label=N_("Box size (photutils)"),
                  visible_when=("backend", ("photutils",))),
        Parameter("subtract", "bool", True, label=N_("Subtract (otherwise: output the model)")),
        Parameter("pedestal", "real", 0.1, 0.0, 1.0, label=N_("Pedestal")),
        Parameter("estimator", "enum", "median",
                  choices=("median", "sextractor", "mmm"),
                  label=N_("Background estimator (photutils)"),
                  visible_when=("backend", ("photutils",))),
        *model_selector_params(visible_when=("backend", ("ai",))),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        background = self._ai_background(data) if self.backend == "ai" \
            else self._photutils_background(data)
        out = (data - background + self.pedestal) if self.subtract else background
        return np.clip(out, 0.0, 1.0).astype(np.float32)

    # --- photutils backend ----------------------------------------------------
    def _photutils_background(self, data: np.ndarray) -> np.ndarray:
        from astropy.stats import SigmaClip
        from photutils.background import (
            Background2D,
            MedianBackground,
            MMMBackground,
            SExtractorBackground,
        )

        estimator = {
            "median": MedianBackground,
            "sextractor": SExtractorBackground,
            "mmm": MMMBackground,
        }[self.estimator]()
        box = int(self.box_size)
        bkg = np.empty_like(data)
        for c in range(data.shape[2]):
            model = Background2D(
                data[:, :, c], (box, box), filter_size=(3, 3),
                sigma_clip=SigmaClip(sigma=3.0), bkg_estimator=estimator,
            )
            bkg[:, :, c] = model.background
        return bkg

    # --- AI backend (GraXpert BGE model) --------------------------------------
    def _ai_background(self, data: np.ndarray) -> np.ndarray:
        """Estimates the background with the network, GraXpert style: downscale → infer → upscale.

        The whole image goes down to 240×240, a mirror border brings it to 256×256 (the
        network's input), a single inference returns the background at that scale, which is then
        smoothed and upscaled back to the original resolution. The model expects three channels:
        a mono image is replicated, and its estimated background broadcast back to all channels.
        """
        from scipy.ndimage import gaussian_filter
        from skimage.transform import resize

        from ..ai.models import resolve
        from ..ai.onnx import open_session

        path, name, version = resolve(str(self.model_id), str(self.model), self.task)
        self._trace_model(path, name, version)
        session = open_session(path)
        entry_name = session.get_inputs()[0].name

        h, w = data.shape[:2]
        useful = _BGE_SIZE - 2 * _BGE_PAD
        self._progress(0.2, _t("Background — downscaling"))
        reduced = resize(data, (useful, useful), order=1, mode="reflect",
                        anti_aliasing=True).astype(np.float32)
        three = (reduced if reduced.shape[2] == 3
                 else np.repeat(reduced.mean(2, keepdims=True), 3, 2))
        bordered = np.pad(three, ((_BGE_PAD, _BGE_PAD), (_BGE_PAD, _BGE_PAD), (0, 0)),
                          mode="reflect")

        median = float(np.median(bordered))
        mad = float(np.median(np.abs(bordered - median))) or 1e-8
        norm = np.clip((bordered - median) / mad * 0.04, -1.0, 1.0).astype(np.float32)

        self._progress(0.5, _t("Background — neural estimate"))
        output = session.run(None, {entry_name: norm[None]})[0][0]
        background = (output / 0.04 * mad + median)[_BGE_PAD:-_BGE_PAD, _BGE_PAD:-_BGE_PAD]
        background = gaussian_filter(background, sigma=(3.0, 3.0, 0.0))

        self._progress(0.8, _t("Background — upscaling"))
        full = resize(background, (h, w), order=1, mode="reflect",
                       anti_aliasing=True).astype(np.float32)
        if full.shape[2] != data.shape[2]:  # mono: broadcast the background to all channels
            full = np.repeat(full.mean(2, keepdims=True), data.shape[2], 2)
        return full

    def execute_on(self, view) -> bool:
        """As in the base class, plus the AI model identity in the keywords (``ai`` backend)."""
        self._identity: tuple[str, str, str] | None = None
        result = super().execute_on(view)
        if result:
            self._write_model_keywords(view)
        return result


@register
class BackgroundNeutralization(Process):
    """Aligns the background of the color channels (removes the background cast)."""

    process_id = "BackgroundNeutralization"
    category = "ColorCalibration"
    parameters = []

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 3:
            return data.copy()
        from astropy.stats import sigma_clipped_stats

        meds = [sigma_clipped_stats(data[:, :, c], sigma=3.0)[1] for c in range(3)]
        target = min(meds)
        out = data.copy()
        for c in range(3):
            out[:, :, c] = data[:, :, c] - (meds[c] - target)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class RollingBallBackground(Process):
    """Background extraction by "rolling ball" (skimage) — fast, an alternative to ABE.

    Rolls a ball of radius ``radius`` under the intensity surface: what it cannot reach = the
    smooth background. ``subtract=False`` outputs the estimated background model.
    """

    process_id = "RollingBallBackground"
    category = "BackgroundModelization"
    parameters = [
        Parameter("radius", "real", 50.0, 1.0, 2000.0, label=N_("Ball radius")),
        Parameter("subtract", "bool", True, label=N_("Subtract (otherwise: output the model)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.restoration import rolling_ball

        r = float(self.radius)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            ch = data[:, :, c]
            bkg = rolling_ball(ch, radius=r)
            out[:, :, c] = (ch - bkg) if self.subtract else bkg
        return np.clip(out, 0.0, 1.0).astype(np.float32)
