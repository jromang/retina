"""Figures for ``ConvertToRGBColor`` — a mono frame promoted to three channels.

The pixels do not change value; what changes is that there are now three of them per site,
so the frame can receive colour. The figure therefore looks the same on both sides, and the
caption is what carries the point — which is why the two are not the same image here: the
right one has had a channel tinted afterwards, to show that the promotion is what made it
possible.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    mono = ctx.crop(ctx.load("field"), 300, 300, 400, 500)
    rgb = retina.ConvertToRGBColor().execute_on_image(mono)
    tinted = np.array(rgb.data, copy=True)
    tinted[:, :, 2] *= 1.6
    ctx.save("before", ctx.autostretch(mono))
    ctx.save("after", ctx.autostretch(rgb.with_data(np.clip(tinted, 0, 1)), reference=mono))
