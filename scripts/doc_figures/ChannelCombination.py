"""Figures for ``ChannelCombination`` — three channels reassembled, swapped.

The source's own R/G/B planes are registered as three separate views, then recombined with the
red and green channels swapped — a real, visible colour reassignment, using only one real
source (no in-repo pair of separately-acquired R/G/B frames exists).
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    app = retina.Application()
    app.new_window(source.with_data(source.data[:, :, 0:1]), window_id="R")
    app.new_window(source.with_data(source.data[:, :, 1:2]), window_id="G")
    app.new_window(source.with_data(source.data[:, :, 2:3]), window_id="B")
    after = retina.ChannelCombination(r="B", g="R", b="G").execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
