"""Figures for ``ArcsinhStretch`` — linear frame in, picture out."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("starfield")
    after = retina.ArcsinhStretch(stretch=150.0, black_point=0.006).execute_on_image(source)
    ctx.save("before", source, flat_on_purpose=True)
    ctx.save("after", after)
