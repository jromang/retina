"""Figures for ``SatelliteTrailDetection`` — the trail found, as a mask.

The trail is **injected**: a straight bright line across a real frame. The process returns a
mask of what it found, so the pair is the frame and that mask rather than a before/after.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 300, 300, 400, 500)
    data = np.array(source.data, copy=True)
    rows = np.arange(400)
    cols = (60 + rows * 0.9).astype(int)
    inside = (cols >= 0) & (cols < 500)
    for offset in (-1, 0, 1):
        data[rows[inside], np.clip(cols[inside] + offset, 0, 499), 0] = 0.9
    streaked = source.with_data(data)
    mask = retina.SatelliteTrailDetection(threshold=0.4, width=3).execute_on_image(streaked)
    ctx.save("source", ctx.autostretch(streaked))
    ctx.save("mask", mask)
