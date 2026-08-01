"""HistogramTransformation — destructive stretch (shadows / midtones / highlights).

Applies the same model as the STF (MTF) to the pixels, but permanently. Used to "bake" an
auto-stretch, or to adjust the black point / gamma / white point by hand.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
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
        # Per-channel triples (shadows, midtones, highlights, …), flat. Empty — the default —
        # means "the three scalars above, on every channel", which is the behaviour this
        # process always had, so recipes and projects written before it read back unchanged.
        # It exists because an auto-stretch is computed **per channel** (`STF.auto_from_image`
        # reads the median of each one), and baking one with a single triple would shift the
        # colour balance of the image it is supposed to reproduce.
        Parameter("channels", "floatlist", [],
                  label=N_("Per channel (shadows, midtones, highlights, …)")),
    ]

    def _triples(self, count: int) -> list[tuple[float, float, float]]:
        """One (shadows, midtones, highlights) per channel."""
        flat = list(self.channels)
        if not flat:
            return [(self.shadows, self.midtones, self.highlights)] * count
        if len(flat) % 3:
            raise ValueError(
                _t("channels expects triples (shadows, midtones, highlights): "
                   "{n} values given.").format(n=len(flat))
            )
        triples = [(flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat), 3)]
        # A channel beyond the list keeps the last triple, as `STF.apply` does — an RGB STF
        # applied to a grey+alpha image must not raise.
        return [triples[min(c, len(triples) - 1)] for c in range(count)]

    @staticmethod
    def _stretch(data: np.ndarray, shadows: float, midtones: float,
                 highlights: float) -> np.ndarray:
        span = max(highlights - shadows, 1e-6)
        xn = np.clip((data - shadows) / span, 0.0, 1.0)
        return np.asarray(mtf(midtones, xn), dtype=np.float32)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        triples = self._triples(data.shape[2])
        if len(set(triples)) == 1:
            return self._stretch(data, *triples[0])
        out = np.empty_like(data, dtype=np.float32)
        for c, triple in enumerate(triples):
            out[:, :, c] = self._stretch(data[:, :, c], *triple)
        return out

    @classmethod
    def from_stf_channel(cls, channel) -> HistogramTransformation:
        """Builds an HT from a single STF channel."""
        return cls(
            shadows=channel.shadows,
            midtones=channel.midtones,
            highlights=channel.highlights,
        )

    @classmethod
    def from_stf(cls, stf) -> HistogramTransformation:
        """Builds the HT that reproduces ``stf`` on the pixels — "bake the screen stretch".

        The gesture the interface offers under the histogram, and the one a script writes as
        ``HistogramTransformation.from_stf(view.stf).execute_on(view)``. Channels that agree
        collapse onto the three scalars, so the common case stays readable in the echo.
        """
        channels = list(stf.channels) if stf is not None else []
        if not channels:
            return cls()
        first = channels[0]
        if all(
            (c.shadows, c.midtones, c.highlights)
            == (first.shadows, first.midtones, first.highlights)
            for c in channels
        ):
            return cls.from_stf_channel(first)
        flat: list[float] = []
        for c in channels:
            flat += [c.shadows, c.midtones, c.highlights]
        return cls(channels=flat)
