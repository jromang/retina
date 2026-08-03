"""Figures for ``ChannelMatch`` — coloured fringes, realigned.

The misalignment is **injected**: the source composite is built band by band on one grid and
carries no lateral chromatic aberration. Shifting the red and blue channels by a pixel and a
half reproduces what a refractor does at the edge of its field, which is the situation this
process exists for.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    base = ctx.crop(ctx.survey(), 280, 280, 340, 420)
    fringed = retina.ChannelMatch(dx=[1.5, 0.0, -1.5], dy=[1.0, 0.0, -1.0]).execute_on_image(base)
    fixed = retina.ChannelMatch(dx=[-1.5, 0.0, 1.5], dy=[-1.0, 0.0, 1.0]).execute_on_image(
        fringed
    )
    ctx.save("before", fringed)
    ctx.save("after", fixed)
