"""Figures for ``SampleFormatConversion`` — quantization made visible.

Three bits, not the sixteen a real conversion uses: at sixteen the difference is below what a
screen shows, and a figure that shows nothing teaches nothing. The banding here is the same
effect, made large enough to look at.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    after = retina.SampleFormatConversion(bits=3).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
