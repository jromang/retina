"""Figures for ``SimplexNoise`` — coherent noise, the kind that models a sky gradient."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.SimplexNoise(octaves=4, scale=8, amount=0.5, seed=0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
