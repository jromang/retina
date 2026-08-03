"""Figures for ``CreateAlphaChannels`` — an alpha channel derived from luminance.

The alpha itself is not a colour, so it is invisible in an opaque render: the ``after`` figure
composites the RGBA result over a flat magenta backdrop (what a transparent-PNG viewer would
show), which is the only way to make ``mode="luminance"`` — opaque where the galaxy is bright,
transparent over the dim sky — actually visible.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    source = ctx.survey()
    rgba = retina.CreateAlphaChannels(mode="luminance").execute_on_image(source)
    rgb, alpha = rgba.data[:, :, :3], rgba.data[:, :, 3:4]
    backdrop = np.array([1.0, 0.0, 1.0], dtype=np.float32)  # magenta: absent from the frame
    composite = rgb * alpha + backdrop * (1.0 - alpha)
    ctx.save("before", source)
    ctx.save("after", composite)
