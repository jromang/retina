"""Figures for ``ExponentialTransformation`` — the SMI curve, on a linear frame.

SMI at order 0.5, not PIP at order 1: order 1 is the identity, and PIP moves a frame this
linear so little that the pair came out as two copies of one picture.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("starfield")
    after = retina.ExponentialTransformation(type="SMI", order=0.5).execute_on_image(source)
    ctx.save("before", source, flat_on_purpose=True)
    ctx.save("after", after)
