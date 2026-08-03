"""Figures for ``Overscan`` — the real overscan strip of a real sensor, used and trimmed.

The Palomar frames of ``ctx.sample`` carry ``BIASSEC`` in their headers, so the section is
read from the file rather than configured by hand — which is the whole point of the process
and the reason this dataset was chosen for the sample catalogue.

The pair is the raw frame, overscan strip and all, and the corrected frame with the strip
subtracted and trimmed away: it is narrower, and the residual read-out level is gone.
"""

from __future__ import annotations

import retina
from retina.io.fits import load_fits, load_fits_header


def figures(ctx) -> None:
    path = str(ctx.sample("example-cryo-lfc") / "ccd.037.0.fits")
    image, _ = load_fits(path)
    header = load_fits_header(path)

    after = retina.Overscan(
        bias_section=header["BIASSEC"], method="median", axis="auto"
    ).execute_on_image(image)

    ctx.save("before", ctx.autostretch(ctx.crop(image, 1500, 1700, 600, 400)))
    ctx.save("after", ctx.autostretch(ctx.crop(after, 1500, 1600, 600, 400)))
