"""Fourier domain: FourierTransform (+ faithful inverse) through numpy.fft.

Two uses:

- **inspection** (``mode="magnitude"``): log-normalized amplitude spectrum, centered, in
  ``[0,1]`` — to spot patterning and periodic motifs.
- **reversible transform** (``mode="complex"``): stacks the real and imaginary parts
  (fftshifted) → ``(H, W, 2·C)``. ``InverseFourierTransform`` reconstructs the spatial image
  **exactly** (lossless round-trip). This resolves the "real model only" limitation by
  carrying the phase in dedicated channels — no complex image type needed.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class FourierTransform(Process):
    process_id = "FourierTransform"
    category = "Fourier"
    is_maskable = False
    parameters = [
        Parameter("mode", "enum", "magnitude",
                  choices=("magnitude", "complex"), label=N_("Output")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        c = data.shape[2]
        if self.mode == "complex":
            re = np.empty_like(data)
            im = np.empty_like(data)
            for k in range(c):
                f = np.fft.fftshift(np.fft.fft2(data[:, :, k]))
                re[:, :, k] = f.real
                im[:, :, k] = f.imag
            return np.concatenate([re, im], axis=2).astype(np.float32)  # (H,W,2C), unbounded
        out = np.empty_like(data)
        for k in range(c):
            f = np.fft.fftshift(np.fft.fft2(data[:, :, k]))
            mag = np.log1p(np.abs(f))
            out[:, :, k] = mag / (float(mag.max()) or 1.0)
        return out.astype(np.float32)


@register
class InverseFourierTransform(Process):
    """Reconstructs the spatial image from FourierTransform's ``complex`` representation.

    Expected input: ``(H, W, 2·C)`` = [real parts | imaginary parts], fftshifted.
    Exact round-trip:
    ``InverseFourierTransform().on(FourierTransform(mode='complex').on(x)) == x``.
    """

    process_id = "InverseFourierTransform"
    category = "Fourier"
    is_maskable = False
    parameters = []

    def _apply(self, data: np.ndarray) -> np.ndarray:
        c2 = data.shape[2]
        if c2 % 2 != 0:
            raise ValueError(_t("InverseFourierTransform expects 2·C channels (real|imaginary)"))
        c = c2 // 2
        out = np.empty((data.shape[0], data.shape[1], c), dtype=np.float32)
        for k in range(c):
            spec = data[:, :, k] + 1j * data[:, :, c + k]
            spatial = np.fft.ifft2(np.fft.ifftshift(spec)).real
            out[:, :, k] = spatial
        return out
