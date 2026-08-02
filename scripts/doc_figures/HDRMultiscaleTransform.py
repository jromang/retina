"""Figures for ``HDRMultiscaleTransform`` — bright cores brought back into range."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 200, 180, 520, 620)
    after = retina.HDRMultiscaleTransform(layers=6).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
