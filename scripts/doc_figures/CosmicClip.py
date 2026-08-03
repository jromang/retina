"""Figures for ``CosmicClip`` — cosmic-ray hits detected and replaced.

The hits are **injected**: a single sub of a real survey composite carries none that survived
stacking. They are the short, bright, sharp-edged streaks a cosmic ray leaves on a sensor —
the thing that distinguishes them from stars, and what the detector keys on.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 300, 300, 400, 500)
    data = np.array(source.data, copy=True)
    rng = np.random.default_rng(4)
    for _ in range(60):
        y, x = rng.integers(20, 380), rng.integers(20, 480)
        length = int(rng.integers(2, 6))
        data[y : y + 1, x : x + length, 0] = 1.0
    hit = source.with_data(data)
    after = retina.CosmicClip(sigclip=4.0, objlim=3.0).execute_on_image(hit)
    ctx.save("before", ctx.autostretch(hit))
    ctx.save("after", ctx.autostretch(after, reference=hit))
