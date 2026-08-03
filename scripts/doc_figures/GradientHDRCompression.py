"""Figures for ``GradientHDRCompression`` — dynamic range compressed in the gradient domain."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 200, 180, 520, 620)
    after = retina.GradientHDRCompression(beta=0.6, alpha=0.1).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
