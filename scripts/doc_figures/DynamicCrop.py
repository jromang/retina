"""Figures for ``DynamicCrop`` — a tilted rectangle, read in one pass.

The ``rotated_rect`` mode rather than the default: it is the one that reads the frame in a
single resampling, so the output is exactly the size of the rectangle drawn. The older mode
rotates *after* cutting, which enlarges the result and leaves black corners.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.DynamicCrop(
        x0=0.22, y0=0.2, x1=0.8, y1=0.74, angle=20.0, mode="rotated_rect"
    ).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
