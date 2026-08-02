"""Figures for ``CurvesTransformation`` — an S-curve on an already stretched image."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    # The classic contrast S: shadows pulled down, highlights pushed up, midpoint fixed.
    after = retina.CurvesTransformation(
        points=[[0.0, 0.0], [0.25, 0.18], [0.5, 0.5], [0.75, 0.82], [1.0, 1.0]]
    ).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
