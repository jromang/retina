"""B3Estimator — estimation by combining two bands (continuum / emission line).

Combines two images of the same field (e.g. a narrowband Hα and a broad "continuum" band) to
isolate the line signal. The scaled continuum is removed: ``out = narrowband − k·continuum``,
where ``k`` is either estimated robustly on the background/stars (sigma-clipped median ratio)
or fixed. numpy/astropy.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class B3Estimator(Process):
    process_id = "B3Estimator"
    category = "ColorCalibration"
    parameters = [
        Parameter("continuum", "view", "", label=N_("Continuum view (broadband)")),
        Parameter("factor", "real", 0.0, 0.0, 100.0, label=N_("k factor (0 = auto)")),
        Parameter("pedestal", "real", 0.05, 0.0, 1.0, label=N_("Pedestal")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.k = None  # factor estimated by the last run

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from ..process import context

        if not self.continuum:
            return data.copy()
        cont = context.resolve_image_full(self.continuum)
        if cont is None or cont.shape[:2] != data.shape[:2]:
            return data.copy()

        nb = data.mean(axis=2) if data.shape[2] > 1 else data[:, :, 0]
        bb = cont.mean(axis=2) if cont.shape[2] > 1 else cont[:, :, 0]

        if self.factor > 0.0:
            k = float(self.factor)
        else:  # auto: robust median ratio where the continuum is significant
            from astropy.stats import sigma_clipped_stats

            _, med, std = sigma_clipped_stats(bb, sigma=3.0)
            mask = bb > med + std  # stars/bright continuum → anchors the ratio
            ratio = nb[mask] / np.maximum(bb[mask], 1e-6)
            k = float(np.median(ratio)) if mask.any() else 1.0
        self.k = k

        estimate = nb - k * bb + self.pedestal
        out = np.clip(estimate, 0.0, 1.0).astype(np.float32)
        if data.shape[2] == 1:
            return out[:, :, None]
        return np.repeat(out[:, :, None], data.shape[2], axis=2)
