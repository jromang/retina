"""Figures for ``GaussianConvolution`` — the reference blur, shown at the pixel scale."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 250, 250, 400, 500)
    after = retina.GaussianConvolution(sigma=3.0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
