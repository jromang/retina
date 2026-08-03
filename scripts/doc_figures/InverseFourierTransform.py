"""Figures for ``InverseFourierTransform`` — back from the frequency domain.

The pair is the magnitude spectrum and the frame the inverse transform gives back. It cannot
be a before/after: a round trip is lossless, so "before" and "after" would be the same
picture — which the generator's own check would rightly call a pair that shows nothing. The
displayed spectrum is the magnitude of the very transform being inverted; the inversion
itself runs on its complex form, magnitude alone having thrown the phase away.
"""

from __future__ import annotations

import retina


def figures(ctx) -> None:
    source = ctx.load("field")
    complex_spectrum = retina.FourierTransform(mode="complex").execute_on_image(source)
    restored = retina.InverseFourierTransform().execute_on_image(complex_spectrum)
    ctx.save("spectrum", retina.FourierTransform(mode="magnitude").execute_on_image(source))
    ctx.save("restored", ctx.autostretch(restored))
