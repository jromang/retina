"""Figures for ``RangeSelection`` — the brightness band selected, as a mask."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    mask = retina.RangeSelection(
        lower=0.15, upper=1.0, fuzziness=0.15, smoothness=2.0
    ).execute_on_image(source)
    ctx.save("source", source)
    ctx.save("mask", mask)
