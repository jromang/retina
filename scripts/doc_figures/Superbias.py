"""Figures for ``Superbias`` — a real master bias, smoothed to its large-scale structure.

The crop sits against the sensor's left edge on purpose: the six raw bias frames of
``ctx.sample("example-cryo-lfc")``, once combined, carry a genuine glow there (amplifier
proximity) on top of the read noise. ``Superbias`` is built to keep exactly that large-scale
shape and remove the pixel-to-pixel grain — a synthetic bias, being noise on a flat pedestal
with nothing large-scale to preserve, would not show the difference between "denoised" and
"erased".
"""

from __future__ import annotations

import numpy as np
import retina
from retina.io.fits import load_fits


def figures(ctx) -> None:
    # `samples.ensure` already returns the folder the archive unpacked to.
    root = ctx.sample("example-cryo-lfc")
    frames = [root / f"ccd.{i:03d}.0.fits" for i in range(1, 7)]
    combined = np.mean([load_fits(str(p))[0].data for p in frames], axis=0).astype(np.float32)
    master_bias = ctx.crop(retina.Image(combined), 0, 0, 900, 900)

    smoothed = retina.Superbias(noise_layers=6).execute_on_image(master_bias)

    # Its own stretch for each: smoothing a master bias collapses its dynamic range to the
    # large-scale structure alone, so the raw frame's stretch renders the result flat grey.
    # The comparison the page needs is pattern against pattern, not level against level.
    ctx.save("before", ctx.autostretch(master_bias))
    ctx.save("after", ctx.autostretch(smoothed))
