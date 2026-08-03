"""Figures for ``LinearFit`` — a frame rescaled onto a reference's level by least squares.

``LinearFit`` matches two views of the *same* field at different levels (a second sub, a
different exposure) — the repository has only one copy of ``field``, so the reference is a
synthetic affine rescale of it (same shape, required: the fit pairs pixels by raveled index).
The fit recovers that exact affine relation, so ``after`` lands on the reference's scale.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    reference = source.with_data((source.data * 0.4 + 0.15).astype(np.float32))
    app = retina.Application()
    app.new_window(reference, window_id="reference")
    after = retina.LinearFit(reference="reference").execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
