"""Figures for ``PixelMath`` — an expression evaluated pixel by pixel.

A square root is the shortest expression that both reads as one and does something visible:
it is a stretch, written as arithmetic rather than chosen from a menu.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.PixelMath(expression="img ** 0.5").execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
