"""Figures for ``FindingChart`` — the field, and the chart drawn from its WCS.

The chart is synthetic: nothing of the image's pixels goes into it. It is drawn from the
astrometric solution alone, which is why it can cover a wider field than the frame does — the
``field_factor`` here widens it to three times the image, the usual reason to make one.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    view = ctx.survey_view()
    retina.FindingChart(
        view_id=view.id, size=800, field_factor=3.0, catalog="gaia", limit_mag=14.0
    ).execute_global(retina.app)
    chart = retina.app.view(f"{view.id}_FindingChart")
    ctx.save("field", view.image)
    ctx.save("chart", chart.image)
