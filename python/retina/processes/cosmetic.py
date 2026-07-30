"""Cosmetics: cosmic ray / hot pixel removal (astroscrappy, LA Cosmic).

astroscrappy applies a noise model calibrated in **real ADU** (gain, read noise). Our images
are normalized to [0,1] → we switch to a 16-bit scale internally so that the noise model
behaves, then switch back to [0,1].
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register

_SCALE = 65535.0


@register
class CosmicClip(Process):
    process_id = "CosmicClip"
    category = "CosmeticCorrection"
    parameters = [
        Parameter("sigclip", "real", 4.5, 0.5, 20.0, label=N_("Sigma clip")),
        Parameter("objlim", "real", 5.0, 0.5, 20.0, label=N_("Object limit")),
        Parameter("iterations", "int", 4, 1, 20, label=N_("Iterations")),
        Parameter("readnoise", "real", 6.5, 0.0, 100.0, label=N_("Read noise (e-)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import astroscrappy

        out = np.empty_like(data)
        for c in range(data.shape[2]):
            scaled = (data[:, :, c].astype(np.float32) * _SCALE)
            _, clean = astroscrappy.detect_cosmics(
                scaled, sigclip=self.sigclip, objlim=self.objlim,
                niter=int(self.iterations), gain=1.0, readnoise=self.readnoise,
            )
            out[:, :, c] = clean / _SCALE
        return np.clip(out, 0.0, 1.0).astype(np.float32)
