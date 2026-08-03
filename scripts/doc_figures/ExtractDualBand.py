"""Figures for ``ExtractDualBand`` — Hα and OIII pulled from a one-shot-colour mosaic.

The repository has no real dual-band OSC raw. The CFA here is built from the survey's own
red/green bands, down-sampled onto their Bayer sites the way a colour sensor would actually
read them: the galaxy genuinely is a different brightness in the red site (Hα) than in the
green sites (OIII), which a mosaic synthesised from a single mono source could not promise.
"""

from __future__ import annotations

import numpy as np
import retina


def _bayer_mosaic(rgb: np.ndarray) -> np.ndarray:
    """RGGB CFA built by picking each Bayer site from the matching real colour band."""
    h, w = rgb.shape[0] - rgb.shape[0] % 2, rgb.shape[1] - rgb.shape[1] % 2
    mosaic = np.zeros((h, w, 1), dtype=np.float32)
    mosaic[0::2, 0::2, 0] = rgb[0:h:2, 0:w:2, 0]   # R site
    mosaic[0::2, 1::2, 0] = rgb[0:h:2, 1:w:2, 1]   # G site
    mosaic[1::2, 0::2, 0] = rgb[1:h:2, 0:w:2, 1]   # G site
    mosaic[1::2, 1::2, 0] = rgb[1:h:2, 1:w:2, 2]   # B site
    return mosaic


def figures(ctx) -> None:
    mosaic = retina.Image(_bayer_mosaic(ctx.survey().data))
    ha = retina.ExtractDualBand(pattern="RGGB", band="ha").execute_on_image(mosaic)
    oiii = retina.ExtractDualBand(pattern="RGGB", band="oiii").execute_on_image(mosaic)
    ctx.save("ha", ha)
    ctx.save("oiii", oiii)
