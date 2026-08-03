"""Figures for ``MultiscaleLinearTransform`` — scale-selective contrast, by starlet layers."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 200, 180, 520, 620)
    after = retina.MultiscaleLinearTransform(
        scales=5, bias=[1.5, 1.0, 0.3, 0.0, 0.0]
    ).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
