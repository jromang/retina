"""Figures for ``HistogramTransformation`` — the manual stretch, on genuinely linear data.

The "before" is the linear frame **as stored**, with no screen stretch: nearly black, three
stars visible. That is what a stacked image looks like, and showing it any other way would
hide the problem the process exists to solve.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("starfield")
    after = retina.HistogramTransformation(
        shadows=0.006, midtones=0.03
    ).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
