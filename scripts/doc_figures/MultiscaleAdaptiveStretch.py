"""Figures for ``MultiscaleAdaptiveStretch`` — an adaptive stretch computed per scale.

Shown on ``data/real_field.fits`` rather than on the linear star field the other stretch pages
use. On data that linear the process barely moves the pixels — the generator's own check
called the pair identical — because there is nothing at the larger scales for it to weigh.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    after = retina.MultiscaleAdaptiveStretch(
        layers=6, noise_threshold=0.005, detail_boost=3.0
    ).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
