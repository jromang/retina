"""Figures for ``Crop`` — the frame reduced to a fraction of itself.

The two images are deliberately of different sizes: that *is* the process. The viewer lays
them side by side at equal width, so the change reads as a change of field rather than of
scale, which is the honest way round.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.Crop(x0=0.28, y0=0.22, x1=0.78, y1=0.76).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
