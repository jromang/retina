"""Star removal (starless).

Backends:
- ``inpaint`` (default, no external dependency): detects the stars (photutils), masks
  them, and reconstructs the background by biharmonic inpainting (scikit-image). Fast,
  testable, correct on sparse fields — not at the level of an AI network.
- ``onnx``: **AI removal** through an ONNX model (StarNet/GraXpert exported to ONNX),
  run by onnxruntime. Tiling + feathering to process large images.
- ``external``: delegates to an AI tool (StarNet++ / GraXpert) through a subprocess
  (``command`` with {input}/{output}). Requires the tool + its model to be installed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register
from .stars import detect_sources, star_mask


@register
class StarRemoval(Process):
    process_id = "StarRemoval"
    category = "MaskGeneration"
    supports_realtime = False  # AI model or inpainting, in a subprocess
    parameters = [
        Parameter(
            "mode", "enum", "inpaint",
            choices=("inpaint", "onnx", "external"), label=N_("Backend"),
        ),
        # --- detection (inpaint mode) ---
        Parameter("fwhm", "real", 3.0, 1.0, 20.0, label=N_("FWHM (detection)")),
        Parameter("threshold_sigma", "real", 5.0, 1.0, 50.0, label=N_("Threshold (σ)")),
        Parameter("radius", "real", 5.0, 1.0, 50.0, label=N_("Masking radius")),
        # --- ONNX backend ---
        Parameter("model", "path", "", label=N_("Model .onnx (StarNet/GraXpert)")),
        Parameter("tile_size", "int", 256, 32, 2048, label=N_("Tile size")),
        Parameter("overlap", "int", 32, 0, 512, label=N_("Overlap (px)")),
        # --- external backend (CLI) ---
        Parameter("command", "str", "", label=N_("AI command ({input} {output})")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if self.mode == "onnx":
            return self._run_onnx(data)
        if self.mode == "external":
            return self._run_external(data)
        return self._inpaint(data)

    # --- inpainting (default) -------------------------------------------------
    def _inpaint(self, data: np.ndarray) -> np.ndarray:
        from skimage.restoration import inpaint_biharmonic

        lum = data.mean(axis=2)
        sources = detect_sources(lum, self.fwhm, self.threshold_sigma)
        mask = star_mask(lum.shape, sources, self.radius)
        if not mask.any():
            return data.copy()
        out = inpaint_biharmonic(data, mask, channel_axis=-1)
        return np.clip(out, 0.0, 1.0).astype(np.float32)

    # --- ONNX AI backend ------------------------------------------------------
    def _run_onnx(self, data: np.ndarray) -> np.ndarray:
        """Delegates to :mod:`retina.ai.onnx` — tiling has nothing star-specific about it."""
        from ..ai.onnx import open_session, run_tiled

        if not self.model:
            raise ValueError(_t("StarRemoval(mode='onnx'): parameter 'model' (.onnx) required."))

        def advance(fraction: float, done: int, total: int) -> None:
            self._progress(fraction, _t("Star removal — tile {n}/{total}").format(
                n=done, total=total))

        res = run_tiled(data, open_session(self.model),
                        tile_size=int(self.tile_size), overlap=int(self.overlap),
                        progress=advance)
        return np.clip(res, 0.0, 1.0).astype(np.float32)

    # --- external AI backend (StarNet/GraXpert CLI) ---------------------------
    def _run_external(self, data: np.ndarray) -> np.ndarray:
        if not self.command:
            raise ValueError(_t("StarRemoval(mode='external'): parameter 'command' required."))
        from ..io.fits import load_fits, save_fits
        from ..model.image import Image
        from ..preferences import temp_root

        with tempfile.TemporaryDirectory(dir=temp_root()) as d:
            inp = os.path.join(d, "in.fits")
            outp = os.path.join(d, "out.fits")
            save_fits(inp, Image(data))
            cmd = self.command.format(input=inp, output=outp)
            subprocess.run(cmd, shell=True, check=True)
            if not os.path.exists(outp):
                raise RuntimeError(
                    _t("StarRemoval: the external tool did not produce {path}").format(path=outp))
            return load_fits(outp)[0].data
