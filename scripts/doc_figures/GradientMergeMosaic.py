"""Figures for ``GradientMergeMosaic`` — two panels of a real star field, glued into one.

The "other" panel is a genuine second view, resolved through the image provider — the same
mechanism the process itself uses (``context.resolve_image_full``), not a stand-in. Panel B
carries a background offset, so the figure also shows the equalization the process performs
over the overlap, not just the geometric fill-in.
"""

from __future__ import annotations

import numpy as np
import retina
from retina.process import context


def figures(ctx) -> None:
    crop = ctx.crop(ctx.load("starfield"), 200, 150, 400, 900)
    data = crop.data

    # Panel A: the left two thirds; the rest is "not observed" (zero, per the process' own
    # convention).
    panel_a = np.zeros_like(data)
    panel_a[:, :600] = data[:, :600]

    # Panel B: the right two thirds, on a slightly different sky level — a real dither between
    # two subs never lands at the exact same background.
    panel_b = np.zeros_like(data)
    panel_b[:, 300:] = np.clip(data[:, 300:] + 0.012, 0.0, 1.0)

    context.set_image_provider({"panel_b": retina.Image(panel_b)}.get)
    try:
        merged = retina.GradientMergeMosaic(other="panel_b").execute_on_image(
            retina.Image(panel_a))
    finally:
        context.set_image_provider(None)

    ctx.save("before", ctx.autostretch(retina.Image(panel_a)))
    ctx.save("after", ctx.autostretch(merged, reference=retina.Image(panel_a)))
