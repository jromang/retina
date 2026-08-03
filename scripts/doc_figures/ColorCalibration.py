"""Figures for ``ColorCalibration`` — gray-world white balance and background neutralization.

No reference views are supplied (both parameters default to empty): the process falls back to
gray-world for the white balance and to the whole image for the background, which is the mode
most users reach for. The source is the uncalibrated composite, whose colour cast is real.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey(balanced=False)
    after = retina.ColorCalibration().execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
