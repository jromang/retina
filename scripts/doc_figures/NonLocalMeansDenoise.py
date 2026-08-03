"""Figures for ``NonLocalMeansDenoise`` — patch-based denoising, at the pixel scale."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 350, 350, 340, 440)
    after = retina.NonLocalMeansDenoise(h=1.6, patch_size=5, patch_distance=6).execute_on_image(
        source
    )
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
