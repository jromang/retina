"""Figures for ``LRGBCombination`` — chrominance kept, luminance replaced.

The repository carries no separate luminance master for the survey field, so the L channel is
synthesized from the source's own luminance with a brightness stretch (``** 0.5``) — a stand-in
for a deeper monochrome exposure, which is the reason anyone runs this process for real. It
must match the source's geometry exactly (no resampling in ``LRGBCombination``), which a
same-source derivation guarantees for free.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    source = ctx.survey()
    deeper_luminance = np.clip(source.data.mean(axis=2), 0.0, 1.0) ** 0.5
    app = retina.Application()
    app.new_window(source.with_data(deeper_luminance[:, :, None].astype(np.float32)),
                    window_id="L")
    after = retina.LRGBCombination(luminance="L", weight=1.0).execute_on_image(source)
    ctx.save("before", source)
    ctx.save("after", after)
