"""Figures for ``SplitCFA`` — the raw Bayer checkerboard, split into its 4 coherent planes.

The mosaic is built from the survey's own bands (see ``ExtractDualBand``): real colour
structure, interleaved onto Bayer sites the way a one-shot-colour sensor would deliver it. The
"after" composites three of the four separated planes (R, one G, B) as a false-colour image —
proof that each plane is already a coherent picture on its own, half the checkerboard's
resolution but none of its aliasing.
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
    survey = ctx.crop(ctx.survey(), 300, 300, 300, 300)
    mosaic = retina.Image(_bayer_mosaic(survey.data))
    planes = retina.SplitCFA().execute_on_image(mosaic)
    # Planes are, in order, R / G / G / B (the 2x2 block read left-right, top-bottom): R, the
    # first G and B recompose a legible false-colour image without the duplicate green.
    composite = planes.data[:, :, (0, 1, 3)]

    ctx.save("mosaic", mosaic)
    ctx.save("planes", np.clip(composite, 0.0, 1.0))
