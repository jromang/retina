"""Figures for ``UnsharpMask`` — local contrast raised, on a crop at the pixel scale."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 250, 250, 400, 500)
    after = retina.UnsharpMask(radius=2.0, amount=0.8).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
