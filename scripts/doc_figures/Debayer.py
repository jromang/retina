"""Figures for ``Debayer`` — a raw Bayer mosaic, reconstructed into full colour.

The repository has no real single-shot-colour raw. The mosaic is built from the survey's own
red/green/blue bands, down-sampled onto their Bayer sites the way a colour sensor would
actually deliver them (see the same construction in ``ExtractDualBand``/``SplitCFA``) — a
genuine colour field driving the interpolation, not an arbitrary synthetic pattern.
"""

from __future__ import annotations

import numpy as np
import retina


def _bayer_mosaic(rgb: np.ndarray) -> np.ndarray:
    h, w = rgb.shape[0] - rgb.shape[0] % 2, rgb.shape[1] - rgb.shape[1] % 2
    mosaic = np.zeros((h, w, 1), dtype=np.float32)
    mosaic[0::2, 0::2, 0] = rgb[0:h:2, 0:w:2, 0]   # R site
    mosaic[0::2, 1::2, 0] = rgb[0:h:2, 1:w:2, 1]   # G site
    mosaic[1::2, 0::2, 0] = rgb[1:h:2, 0:w:2, 1]   # G site
    mosaic[1::2, 1::2, 0] = rgb[1:h:2, 1:w:2, 2]   # B site
    return mosaic


def figures(ctx) -> None:
    survey = ctx.crop(ctx.survey(), 300, 300, 320, 320)
    mosaic = retina.Image(_bayer_mosaic(survey.data))
    rgb = retina.Debayer(pattern="RGGB", method="malvar").execute_on_image(mosaic)

    ctx.save("mosaic", mosaic)
    ctx.save("debayered", rgb)
