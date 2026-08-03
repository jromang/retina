"""Figures for ``MergeCFA`` — the four CFA planes, interleaved back into one mosaic.

The inverse of ``SplitCFA``: starts from the false-colour composite of the split planes (what
one would see after calibrating or denoising each site on its own) and reassembles the single
raw-looking plane a debayer expects. Built from the survey's real bands, like ``SplitCFA`` and
``ExtractDualBand``, but over a different crop of the field so the two pages are not showing
the same pixels twice.
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
    survey = ctx.crop(ctx.survey(), 420, 420, 300, 300)
    source_mosaic = retina.Image(_bayer_mosaic(survey.data))
    planes = retina.SplitCFA().execute_on_image(source_mosaic)
    merged = retina.MergeCFA().execute_on_image(planes)

    composite = np.clip(planes.data[:, :, (0, 1, 3)], 0.0, 1.0)
    ctx.save("planes", composite)
    ctx.save("mosaic", merged)
