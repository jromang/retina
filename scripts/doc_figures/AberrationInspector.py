"""Figures for ``AberrationInspector`` — the corners of a frame, side by side.

The whole point is that optical faults live at the edges and nobody scrolls to nine of them
in turn. The mosaic puts the corners, the edges and the centre in one view, at the pixel
scale — a tile larger than the frame allows is cropped, never enlarged, because enlarging
pixels would invent an aberration.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("starfield")
    mosaic = retina.AberrationInspector(mosaic_size=3, panel_size=256).execute_on_image(source)
    ctx.save("frame", ctx.autostretch(source))
    ctx.save("mosaic", ctx.autostretch(mosaic, reference=source))
