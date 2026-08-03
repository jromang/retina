"""Figures for ``SurveyReference`` — your field, and the same field from a sky survey.

The pair is the point of the process: the reference arrives resolved and framed on *your*
WCS, so it can be blinked against the image and then handed to
``MultiscaleGradientCorrection``. Shown against DSS2 red, a different survey from the one the
source composite is made of — which is the realistic case, and the one that proves the method
does not need the two to be photometrically related.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    view = ctx.survey_view()
    retina.SurveyReference(view_id=view.id, survey="dss2-red", max_size=600).execute_global(
        retina.app
    )
    reference = retina.app.view(f"{view.id}_dss2-red")
    ctx.save("field", view.image)
    ctx.save("reference", ctx.autostretch(reference.image))
