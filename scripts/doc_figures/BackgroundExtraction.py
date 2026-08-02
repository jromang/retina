"""Figures for ``BackgroundExtraction`` — a real sky gradient, removed.

``data/real_field.fits`` is a genuine frame with a genuine gradient, which matters here: a
synthetic ramp is removed perfectly by any method, so it would illustrate nothing.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    after = retina.BackgroundExtraction(box_size=64).execute_on_image(source)
    # One stretch for both, taken from the *source*: computing a second one on the corrected
    # image would renormalise away the very difference the pair exists to show.
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
