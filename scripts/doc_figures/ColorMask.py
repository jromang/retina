"""Figures for ``ColorMask`` — a hue range selected, as a mask.

Yellow-orange, because that is what the source actually holds: the composite is uncalibrated
and its galaxy runs warm. A blue range was the first try and selected nothing — which is the
page's own warning about hue ranges, learnt the direct way.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    mask = retina.ColorMask(
        hue_center=50.0, hue_width=60.0, fuzziness=25.0,
        min_saturation=0.05, min_lightness=0.08,
    ).execute_on_image(source)
    ctx.save("source", source)
    ctx.save("mask", mask)
