"""Figures for ``Convolution`` — the Laplacian kernel, which is the one worth seeing.

A box kernel rather than the Gaussian ``GaussianConvolution`` already shows: at the same
radius the two differ in exactly the way this page is about — the box weights every pixel of
its neighbourhood equally and leaves the square-edged smear that gives it away.

The Laplacian was the first choice and failed the generator's own check: on a smooth sky its
output sits so close to zero that the pair showed nothing.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 250, 250, 400, 500)
    after = retina.Convolution(filter="box", radius=6.0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
