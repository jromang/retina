"""Figures for ``WaveletTransform`` — detail layers amplified, approximation left alone."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 200, 180, 520, 620)
    after = retina.WaveletTransform(
        wavelet="db2", level=3, approx_gain=1.0, detail_gain=2.5
    ).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
