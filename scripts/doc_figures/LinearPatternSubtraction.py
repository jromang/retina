"""Figures for ``LinearPatternSubtraction`` — column banding removed.

The banding is **injected**: a repeating offset added column by column, which is what an
uncorrected sensor read-out leaves and what the LPS step of the pipeline removes before
debayering (after it, interpolation has mixed the pattern between colours and it is no longer
separable).
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 300, 300, 400, 500)
    data = np.array(source.data, copy=True)
    rng = np.random.default_rng(11)
    data[:, :, 0] += rng.normal(0, 0.02, data.shape[1])[None, :]
    banded = source.with_data(np.clip(data, 0.0, 1.0))
    after = retina.LinearPatternSubtraction(columns=True).execute_on_image(banded)
    ctx.save("before", ctx.autostretch(banded))
    ctx.save("after", ctx.autostretch(after, reference=banded))
