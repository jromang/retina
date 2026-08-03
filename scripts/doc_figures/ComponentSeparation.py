"""Figures for ``ComponentSeparation`` — the RGB channels decomposed into PCA components.

Shown as ``source``/``components`` rather than ``before``/``after``: the output is not a
retouched version of the input, it is a different basis over the same three channels (the
first component captures what is correlated across R/G/B, the others the residuals).
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.survey()
    components = retina.ComponentSeparation(method="pca").execute_on_image(source)
    ctx.save("source", source)
    ctx.save("components", components)
