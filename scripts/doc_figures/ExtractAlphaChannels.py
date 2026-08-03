"""Figures for ``ExtractAlphaChannels`` — the alpha channel pulled into its own window.

The source is built with ``CreateAlphaChannels(mode="luminance")`` so the alpha is not a flat
constant — a uniform alpha would pass the "not flat" check for the wrong reason (it would look
like any other grey rectangle, not like a mask).
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    rgba = retina.CreateAlphaChannels(mode="luminance").execute_on_image(ctx.survey())
    alpha = retina.ExtractAlphaChannels(mode="extract").execute_on_image(rgba)
    ctx.save("rgb", rgba.with_data(rgba.data[:, :, :3]))
    ctx.save("alpha", alpha)
