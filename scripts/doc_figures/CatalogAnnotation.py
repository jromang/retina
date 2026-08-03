"""Figures for ``CatalogAnnotation`` — Gaia DR3 objects marked on a solved field.

In ``pixels`` mode, the only mode a figure can show; the default ``overlay`` draws in the
viewport and leaves the data untouched, which is what you want in the application and
useless in a picture.

The limiting magnitude and the marker radius are pushed well past their defaults. At
magnitude 12 and a six-pixel radius the annotation is a handful of thin circles on a 900-pixel
field — correct, and invisible once the page scales the image down.
"""

from __future__ import annotations

import numpy as np
import retina


def figures(ctx) -> None:
    view = ctx.survey_view()
    before = view.image.with_data(np.array(view.image.data, copy=True))
    retina.CatalogAnnotation(
        render_mode="pixels", limit_mag=20.0, max_objects=800, marker_radius=16.0
    ).execute_on(view)
    ctx.save("before", before)
    ctx.save("after", view.image)
