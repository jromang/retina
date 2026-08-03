"""Figures for ``CosmeticCorrection`` — hot and cold pixels replaced by the local median.

``starfield`` carries no known sensor defect, so hot (value 1.0) and cold (value 0.0) pixels
are injected at random positions on a crop — exactly the static per-pixel defect this process
targets, as opposed to ``CosmicClip``'s cosmic rays. Injected here, said here.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("starfield"), 260, 340, 100, 100)
    data = source.data.copy()
    rng = np.random.default_rng(1)
    hot_y, hot_x = rng.integers(3, 97, 100), rng.integers(3, 97, 100)
    cold_y, cold_x = rng.integers(3, 97, 60), rng.integers(3, 97, 60)
    data[hot_y, hot_x, 0] = 1.0
    data[cold_y, cold_x, 0] = 0.0
    defected = source.with_data(data)

    after = retina.CosmeticCorrection(hot_sigma=3.0, cold_sigma=3.0).execute_on_image(defected)
    ctx.save("before", ctx.autostretch(defected))
    ctx.save("after", ctx.autostretch(after, reference=defected))
