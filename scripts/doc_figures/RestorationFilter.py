"""Figures for ``RestorationFilter`` — Wiener deconvolution, direct and non-iterative."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("starfield"), 260, 340, 420, 560)
    after = retina.RestorationFilter(
        psf_sigma=2.0, balance=0.3, mode="wiener"
    ).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
