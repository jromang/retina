"""Noise generation: NoiseGenerator (gaussian/poisson/uniform) and SimplexNoise.

Useful for testing denoising pipelines, simulating frames, or generating background
textures. Pure numpy (in-house fractal value noise for the simplex, with no external
dependency).
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class NoiseGenerator(Process):
    """Adds noise to the image (gaussian, poisson or uniform)."""

    process_id = "NoiseGenerator"
    category = "NoiseGeneration"
    parameters = [
        Parameter("type", "enum", "gaussian",
                  choices=("gaussian", "poisson", "uniform"), label=N_("Type")),
        Parameter("amount", "real", 0.05, 0.0, 1.0, label=N_("Amplitude")),
        Parameter("seed", "int", 0, 0, 2**31 - 1, label=N_("Seed")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        rng = np.random.default_rng(int(self.seed))
        a = float(self.amount)
        if self.type == "gaussian":
            out = data + rng.normal(0.0, a, data.shape)
        elif self.type == "uniform":
            out = data + rng.uniform(-a, a, data.shape)
        else:  # poisson: signal-dependent noise
            scale = max(a, 1e-6) * 1000.0
            out = rng.poisson(np.clip(data, 0, 1) * scale) / scale
        return np.clip(out, 0.0, 1.0).astype(np.float32)


def _value_noise(shape, cells, rng):
    """Smooth value noise: a coarse random grid, interpolated (order 3)."""
    from scipy.ndimage import zoom

    h, w = shape
    coarse = rng.random((max(2, cells), max(2, cells)))
    zy, zx = h / coarse.shape[0], w / coarse.shape[1]
    field = zoom(coarse, (zy, zx), order=3)[:h, :w]
    return field


@register
class SimplexNoise(Process):
    """Generates smooth fractal noise (a sum of value-noise octaves) and blends it in.

    Approximates simplex noise with no dependency: several octaves of interpolated value
    noise, of decreasing amplitude. ``amount`` = blending weight with the image.
    """

    process_id = "SimplexNoise"
    category = "NoiseGeneration"
    parameters = [
        Parameter("octaves", "int", 4, 1, 8, label=N_("Octaves")),
        Parameter("scale", "int", 8, 2, 256, label=N_("Cells (base scale)")),
        Parameter("amount", "real", 0.5, 0.0, 1.0, label=N_("Blend")),
        Parameter("seed", "int", 0, 0, 2**31 - 1, label=N_("Seed")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        rng = np.random.default_rng(int(self.seed))
        h, w = data.shape[:2]
        field = np.zeros((h, w), dtype=np.float64)
        amp, total = 1.0, 0.0
        for o in range(int(self.octaves)):
            field += amp * _value_noise((h, w), int(self.scale) * (2**o), rng)
            total += amp
            amp *= 0.5
        field /= max(total, 1e-6)
        field = (field - field.min()) / (float(np.ptp(field)) or 1.0)  # normalize to [0,1]
        blend = float(self.amount)
        out = data * (1.0 - blend) + field[:, :, None] * blend
        return np.clip(out, 0.0, 1.0).astype(np.float32)
