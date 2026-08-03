"""Figures for ``Rotation`` — an arbitrary angle, with the corners it costs.

Thirty degrees rather than a small angle: the point a figure has to make is that a free
rotation resamples every pixel and enlarges the frame to fit, leaving black corners that a
later crop has to remove.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.Rotation(angle=30.0, order=3).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
