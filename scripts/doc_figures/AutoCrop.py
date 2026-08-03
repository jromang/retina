"""Figures for ``AutoCrop`` — the black margins a rotation leaves, taken off.

The margins are not staged: they are what ``Rotation`` produces, and removing them is the
step that normally follows it.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    rotated = retina.Rotation(angle=15.0, order=3).execute_on_image(ctx.survey())
    after = retina.AutoCrop(coverage=0.98, max_fraction=0.35).execute_on_image(rotated)
    ctx.save("before", rotated)
    ctx.save("after", after)
