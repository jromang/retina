"""Figures for ``StarReduction`` — stars shrunk, the rest untouched.

``morphological`` is the method shown because it is the one that needs no starless image:
a figure that first required a neural network model would not be regenerable on a checkout.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("starfield"), 260, 340, 420, 560)
    after = retina.StarReduction(
        method="morphological", strength=0.6, iterations=2
    ).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
