"""HistogramTransformation — destructive stretch (shadows / midtones / highlights).

Applies the same model as the STF (MTF) to the pixels, but permanently. Used to "bake" an
auto-stretch, or to adjust the black point / gamma / white point by hand.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..model.stf import mtf
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class HistogramTransformation(Process):
    process_id = "HistogramTransformation"
    category = "IntensityTransformations"
    parameters = [
        Parameter("shadows", "real", 0.0, 0.0, 1.0, label=N_("Shadows (black point)")),
        Parameter("midtones", "real", 0.5, 0.0, 1.0, label=N_("Midtones")),
        Parameter("highlights", "real", 1.0, 0.0, 1.0, label=N_("Highlights (white point)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        span = max(self.highlights - self.shadows, 1e-6)
        xn = np.clip((data - self.shadows) / span, 0.0, 1.0)
        return np.asarray(mtf(self.midtones, xn), dtype=np.float32)

    @classmethod
    def from_stf_channel(cls, channel) -> HistogramTransformation:
        """Builds an HT from an STF channel (to bake an auto-stretch)."""
        return cls(
            shadows=channel.shadows,
            midtones=channel.midtones,
            highlights=channel.highlights,
        )
