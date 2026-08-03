"""Figures for ``NoiseGenerator`` — noise added on purpose, to test what removes it."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.NoiseGenerator(type="gaussian", amount=0.08, seed=0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
