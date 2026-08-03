"""Figures for ``WaveletDenoise`` — thresholding the finest wavelet scales."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 350, 350, 340, 440)
    after = retina.WaveletDenoise(wavelet="db2", level=3, threshold=4.0).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
