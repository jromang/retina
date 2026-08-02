"""Figures for ``LocalHistogramEqualization`` — local contrast, on nebulosity."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 200, 180, 520, 620)
    after = retina.LocalHistogramEqualization(
        clip_limit=0.02, kernel_size=128
    ).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
