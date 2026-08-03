"""Figures for ``MultiscaleGradientCorrection`` — a starlet-residual gradient, removed.

No reference supplied: the process falls back to its blind mode (large-scale = gradient),
which is exactly what the real gradient of ``data/real_field.fits`` calls for.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    after = retina.MultiscaleGradientCorrection(scale=7, pedestal=0.1).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
