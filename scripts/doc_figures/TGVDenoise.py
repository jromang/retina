"""Figures for ``TGVDenoise`` — total generalized variation, on a crop at the pixel scale."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 350, 350, 340, 440)
    after = retina.TGVDenoise(strength=0.15, iterations=100).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
