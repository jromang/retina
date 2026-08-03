"""Figures for ``AutoHistogram`` — the background driven to a target level, automatically."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("starfield")
    after = retina.AutoHistogram(target_background=0.25).execute_on_image(source)
    ctx.save("before", source, flat_on_purpose=True)
    ctx.save("after", after)
