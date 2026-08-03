"""Figures for ``Invert`` — the photographic negative, one minus the pixel."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.Invert().execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
