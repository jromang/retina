"""Figures for ``Annotation`` — a coordinate grid drawn over a solved field.

Shown in ``pixels`` mode, which is the only mode a figure can show: the default ``overlay``
draws in the viewport and leaves the data alone, on purpose.

The grid spacing is not the default. At 0.5 degrees, on a field a quarter of a degree wide,
no line of the grid falls inside the frame and the process appears to do nothing — which is
worth knowing before blaming the process.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    view = ctx.survey_view()
    before = view.image.with_data(np.array(view.image.data, copy=True))
    retina.Annotation(render_mode="pixels", grid_spacing=0.05).execute_on(view)
    ctx.save("before", before)
    ctx.save("after", view.image)
