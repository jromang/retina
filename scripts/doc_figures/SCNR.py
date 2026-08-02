"""Figures for ``SCNR`` — the green cast removed.

No cast is staged here: an uncalibrated three-band composite has a real one (see
``FigureContext.survey``), which is precisely the situation this process exists for.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.SCNR(channel="G", protection="average", amount=1.0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
