"""Figures for ``RickerWaveletEnhance`` — structures of one chosen width brought out."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 200, 180, 520, 620)
    after = retina.RickerWaveletEnhance(width=3.0, amount=6.0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
