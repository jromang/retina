"""Figures for ``ColorSaturation`` — saturation raised, hue and luminance kept."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.ColorSaturation(saturation=2.0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
