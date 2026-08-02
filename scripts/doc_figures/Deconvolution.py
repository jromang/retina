"""Figures for ``Deconvolution`` — stars tightened, at the pixel scale.

Shown on a **crop**: a 900 px-wide reduction of a full frame averages away the very thing a
deconvolution changes, and the page would show two identical rectangles.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("starfield"), 260, 340, 420, 560)
    # The settings matter as much as the process. A bare Richardson-Lucy at 30 iterations
    # gave a figure showing exactly what the page tells the reader to avoid — dark rings
    # around every star and background noise amplified into blotches. Regularisation and
    # deringing are what an actual deconvolution run uses, so they are what the figure shows.
    after = retina.Deconvolution(
        psf_mode="parametric",
        psf_sigma=2.0,
        iterations=8,
        regularization=3.0,
        dering_dark=0.8,
    ).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
