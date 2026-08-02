"""Figures for ``StarMask`` — the source field, and the mask it produces.

A mask is not a "before/after": the pair to show is the image and what the process selects in
it. Named accordingly, so the Markdown reads ``figures/source.webp`` and ``figures/mask.webp``.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("starfield"), 260, 340, 420, 560)
    mask = retina.StarMask(fwhm=3.0, threshold_sigma=5.0, radius=4.0).execute_on_image(source)
    ctx.save("source", ctx.autostretch(source))
    # A mask is already in [0,1] and means nothing stretched: it is shown as it will be used.
    ctx.save("mask", mask)
