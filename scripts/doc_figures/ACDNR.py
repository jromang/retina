"""Figures for ``ACDNR`` — chrominance-aware denoising with a protection threshold."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 350, 350, 340, 440)
    after = retina.ACDNR(sigma=3.0, protection=0.3).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
