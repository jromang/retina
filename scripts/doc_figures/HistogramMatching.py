"""Figures for ``HistogramMatching`` — a frame's intensity distribution matched to another's.

The reference is ``starfield``, whose histogram (mostly near-zero background, a sparse bright
tail) is very different from ``field``'s: matching gives a visibly different tonal balance,
not a subtle one. The reference is registered as a window so ``reference`` can name it by id.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    reference = ctx.load("starfield")
    app = retina.Application()
    app.new_window(reference, window_id="reference")
    after = retina.HistogramMatching(reference="reference").execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
