"""Figures for ``AdaptiveStretch`` — the curve derived from the image, not from a slider."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("starfield")
    after = retina.AdaptiveStretch(noise_threshold=0.002).execute_on_image(source)
    ctx.save("before", source, flat_on_purpose=True)
    ctx.save("after", after)
