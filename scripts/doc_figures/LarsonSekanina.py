"""Figures for ``LarsonSekanina`` — the rotational gradient filter, on a spiral.

Written for comets, where it lifts jets out of the coma; the same rotational difference
brings out the arms of a face-on galaxy, which is what is available here to photograph.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.crop(ctx.survey(), 200, 180, 520, 620)
    after = retina.LarsonSekanina(angle=8.0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
