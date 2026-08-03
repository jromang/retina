"""Figures for ``Binarize`` — everything above the threshold becomes one, the rest zero."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.Binarize(threshold=0.2).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
