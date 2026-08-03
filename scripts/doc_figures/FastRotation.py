"""Figures for ``FastRotation`` — a quarter turn, exact and lossless.

Unlike ``Rotation``, nothing is interpolated and no corner is lost: the pixels are the same
pixels, in another order. The figure shows the 90 degree case, where that is plain.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.FastRotation(operation="rotate90").execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
