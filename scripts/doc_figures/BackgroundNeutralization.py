"""Figures for ``BackgroundNeutralization`` — a coloured sky brought back to neutral.

The source is an uncalibrated composite, so its sky is genuinely off-neutral: the figure
shows the process on the defect it was written for, not on one added for the picture.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey(balanced=False)
    after = retina.BackgroundNeutralization().execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
