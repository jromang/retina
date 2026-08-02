"""Figures for ``GradientCorrection`` — a polynomial surface subtracted from the sky."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    after = retina.GradientCorrection(degree=2).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
