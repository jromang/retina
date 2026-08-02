"""Figures for ``MorphologicalTransformation`` — erosion, at the pixel scale."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("starfield"), 260, 340, 420, 560)
    after = retina.MorphologicalTransformation(
        operation="erosion", size=3
    ).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
