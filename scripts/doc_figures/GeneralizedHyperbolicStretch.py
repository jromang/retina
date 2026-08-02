"""Figures for ``GeneralizedHyperbolicStretch`` — linear frame in, picture out.

"Before" is the linear frame as stored, with no screen stretch (see
``HistogramTransformation``'s module): the point of the pair is what the stretch makes
visible, not how the viewport happens to preview it.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("starfield")
    after = retina.GeneralizedHyperbolicStretch(
        stretch_factor=3.0, local_intensity=0.5, symmetry_point=0.01
    ).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
