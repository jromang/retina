"""Figures for ``FourierTransform`` — the field, and its magnitude spectrum.

Not a before/after: the spectrum is another way of looking at the same frame. Diagonal
streaks in it are periodic structure in the image, which is what one comes here to find.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    spectrum = retina.FourierTransform(mode="magnitude").execute_on_image(source)
    ctx.save("source", ctx.autostretch(source))
    ctx.save("spectrum", spectrum)
