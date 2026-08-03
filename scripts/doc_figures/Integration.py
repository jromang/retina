"""Figures for ``Integration`` — one frame against the stack of six.

Bias frames, not lights, and that is deliberate: the dataset carries a single light per
filter, and a bias frame is nothing *but* noise, so stacking shows exactly what stacking is
for. Six frames should divide the noise by about the square root of six, and the pair is that
factor made visible — the same argument that makes an astrophotographer shoot all night.

Both are shown with their own screen stretch: a shared one would flatten the result, since
the whole effect is a change in the spread of the values rather than in their level.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    root = ctx.sample("example-cryo-lfc")
    frames = [str(root / f"ccd.{i:03d}.0.fits") for i in range(1, 7)]

    single = ctx.crop(retina.app.open(frames[0]).main_view.image, 1200, 400, 500, 700)
    retina.Integration(frames=frames, rejection="auto").execute_global(retina.app)
    stacked = ctx.crop(retina.app.view("integration").image, 1200, 400, 500, 700)

    ctx.save("single", ctx.autostretch(single))
    ctx.save("stacked", ctx.autostretch(stacked))
