"""Figures for ``IntegerResample`` — binning by an integer factor.

Unlike ``Resample``, nothing is interpolated: whole blocks of pixels are averaged, which is
what a camera does when it bins on the sensor.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 300, 300, 300, 380)
    after = retina.IntegerResample(
        factor=3, mode="downsample", downsample_op="average"
    ).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
