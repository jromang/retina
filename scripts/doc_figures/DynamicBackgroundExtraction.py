"""Figures for ``DynamicBackgroundExtraction`` — an RBF model through hand-placed samples.

The samples form a coarse grid over the real gradient of ``data/real_field.fits``, the same
source ``BackgroundExtraction`` uses — a synthetic ramp would be fitted perfectly by any
model, sample placement included, and would show nothing about the samples themselves.
"""

from __future__ import annotations

import retina


def _grid_samples(width: int, height: int) -> list[tuple[int, int]]:
    xs = (width // 8, width // 2, width - width // 8)
    ys = (height // 8, height // 2, height - height // 8)
    return [(x, y) for x in xs for y in ys]


def figures(ctx) -> None:
    source = ctx.load("field")
    height, width = source.data.shape[:2]
    after = retina.DynamicBackgroundExtraction(
        samples=_grid_samples(width, height), model="rbf", sample_radius=15,
        subtract=True, pedestal=0.1,
    ).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
