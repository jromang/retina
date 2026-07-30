"""Debayering (CFA → RGB) through colour-demosaicing."""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class Debayer(Process):
    process_id = "Debayer"
    category = "Debayer"
    supports_realtime = False  # the CFA mosaic does not survive decimation
    parameters = [
        Parameter("pattern", "enum", "RGGB",
                  choices=("RGGB", "BGGR", "GRBG", "GBRG"), label=N_("CFA pattern")),
        Parameter("method", "enum", "bilinear", choices=("bilinear", "malvar"), label=N_("Method")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] != 1:
            return data.copy()  # already in color
        cfa = data[:, :, 0].astype(np.float32)
        if self.method == "malvar":
            from colour_demosaicing import demosaicing_CFA_Bayer_Malvar2004 as demo
        else:
            from colour_demosaicing import demosaicing_CFA_Bayer_bilinear as demo
        rgb = np.asarray(demo(cfa, pattern=self.pattern))
        return np.clip(rgb, 0.0, 1.0).astype(np.float32)
