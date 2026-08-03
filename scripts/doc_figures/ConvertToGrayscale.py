"""Figures for ``ConvertToGrayscale`` — colour collapsed to weighted luminance."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.ConvertToGrayscale().execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
