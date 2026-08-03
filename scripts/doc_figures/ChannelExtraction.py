"""Figures for ``ChannelExtraction`` — the luminance pulled out of a colour frame."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    luminance = retina.ChannelExtraction(channel="L").execute_on_image(source)
    ctx.save("source", source)
    ctx.save("luminance", luminance)
