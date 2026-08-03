"""Figures for ``SEPBackground`` — the ``sep`` (Source Extractor) background model, subtracted.

Same real gradient as ``BackgroundExtraction``: the point of this page is that ``sep`` is a
fast alternative on wide fields, not a different result, so it needs to be shown flattening a
genuine gradient rather than a synthetic one.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    after = retina.SEPBackground(box_size=64, subtract=True).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
