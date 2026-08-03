"""Figures for ``ImageCalibration`` — a real Palomar light frame, bias/dark/flat corrected.

The masters are combined (plain mean, a handful of frames each) from the real bias, dark and
flat frames of ``ctx.sample("example-cryo-lfc")`` — the same night's calibration set the
frame itself comes from, not stand-ins. The crop sits on a field of real stars so the effect
of subtracting the sky pedestal is visible alongside the flat's correction of the sensor's own
structure.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import retina
from retina.io.fits import load_fits, save_fits


def _combine(paths: list[Path]) -> np.ndarray:
    """Plain mean of a handful of real calibration frames — not a full ``Integration``."""
    return np.mean([load_fits(str(p))[0].data for p in paths], axis=0).astype(np.float32)


def figures(ctx) -> None:
    # `samples.ensure` already returns the folder the archive unpacked to.
    root = ctx.sample("example-cryo-lfc")
    bias_frames = [root / f"ccd.{i:03d}.0.fits" for i in range(1, 7)]
    flat_frames = [root / f"ccd.{i:03d}.0.fits" for i in (14, 15, 16)]  # g' flats
    dark_frames = [root / "darks" / f"ccd.{i:03d}.0.fits" for i in (13, 14, 15)]  # 300 s
    light = load_fits(str(root / "ccd.037.0.fits"))[0]  # g' light, 300 s, VV124

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bias_path = tmp / "bias.fits"
        dark_path = tmp / "dark.fits"
        flat_path = tmp / "flat.fits"
        save_fits(str(bias_path), retina.Image(_combine(bias_frames)))
        save_fits(str(dark_path), retina.Image(_combine(dark_frames)))
        save_fits(str(flat_path), retina.Image(_combine(flat_frames)))

        calibrated = retina.ImageCalibration(
            master_bias=str(bias_path), master_dark=str(dark_path), master_flat=str(flat_path),
        ).execute_on_image(light)

    before = ctx.crop(light, 1550, 0, 500, 700)
    after = ctx.crop(calibrated, 1550, 0, 500, 700)
    # Each frame gets **its own** stretch here, against the rule that governs every other
    # pair in this folder. Calibration removes the bias pedestal on purpose, so the two
    # frames no longer share a level: stretched against the raw one, the calibrated frame
    # came out black. What the pair has to show is the structure — the sensor pattern and
    # the dust motes the flat divides out — and that survives an independent stretch.
    ctx.save("raw", ctx.autostretch(before))
    ctx.save("calibrated", ctx.autostretch(after))
