"""Figures for ``MultiscaleMedianTransform`` — small scales attenuated, structures kept."""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.load("field"), 350, 350, 340, 440)
    after = retina.MultiscaleMedianTransform(
        scales=4, bias=[-1.0, -0.5, 0.0, 0.0]
    ).execute_on_image(source)
    ctx.save("before", ctx.autostretch(source))
    ctx.save("after", ctx.autostretch(after, reference=source))
