"""Figures for ``Resample`` — a downscale, shown at the pixel scale.

The crop is small on purpose. Reduced to a third and then laid beside the original at the
page's width, the resampled frame is stretched back up by the browser, which is exactly how
the loss of detail becomes visible — and exactly what happens when one resamples too far.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 300, 300, 300, 380)
    after = retina.Resample(scale=0.33, order=3).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
