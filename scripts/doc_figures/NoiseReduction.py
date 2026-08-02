"""Figures for ``NoiseReduction`` — grain removed without flattening the stars.

On a crop, and on a real frame: denoising is judged at the pixel scale, and on synthetic
Gaussian noise every method looks perfect.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 350, 350, 340, 440)
    after = retina.NoiseReduction(method="tv", strength=0.15).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
