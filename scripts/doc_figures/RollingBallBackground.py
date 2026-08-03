"""Figures for ``RollingBallBackground`` — a real sky gradient, removed by the rolling ball.

Same source as ``BackgroundExtraction``/``DynamicBackgroundExtraction``: a genuine gradient,
so the flattening shown here is a real correction and not the trivial removal of a synthetic
ramp.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    after = retina.RollingBallBackground(radius=60.0, subtract=True).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
