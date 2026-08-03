"""Figures for ``PixelInterpolation`` — missing pixels filled from their neighbours.

The holes are **injected** (set to zero), because a frame that reaches the documentation has
already been through calibration and has none left. That is the input this process expects:
a defect map has marked pixels as unusable and something has to stand in for them.

``mark_zeros=True`` is not decoration: with the default the process leaves a zero alone,
treating it as a legitimate value, and the figure came back identical on both sides.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 300, 300, 400, 500)
    data = np.array(source.data, copy=True)
    rng = np.random.default_rng(7)
    ys = rng.integers(0, 400, 4000)
    xs = rng.integers(0, 500, 4000)
    data[ys, xs, 0] = 0.0
    data[120:150, 150:450, 0] = 0.0  # a dead patch, the other shape a defect takes
    data[:, 60:66, 0] = 0.0  # and a dead column, which is the commonest of all
    holed = source.with_data(data)
    after = retina.PixelInterpolation(sigma=2.0, mark_zeros=True).execute_on_image(holed)
    ctx.save("before", ctx.autostretch(holed))
    ctx.save("after", ctx.autostretch(after, reference=holed))
