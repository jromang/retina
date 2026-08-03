"""Figures for ``MaskedStretch`` — the background raised to target, star cores spared."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("starfield")
    after = retina.MaskedStretch(target_background=0.25).execute_on_image(source)
    ctx.save("before", source, flat_on_purpose=True)
    ctx.save("after", after)
