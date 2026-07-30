"""GaussianConvolution — the first process backed by a native Rust operator."""

from __future__ import annotations

import numpy as np

from ..backend import gaussian_convolve
from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class GaussianConvolution(Process):
    process_id = "GaussianConvolution"
    category = "Convolution"
    parameters = [
        Parameter(
            "sigma",
            "real",
            default=2.0,
            min=0.0,
            max=50.0,
            label=N_("Sigma"),
            tooltip=N_("Standard deviation of the Gaussian kernel (pixels)."),
        )
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        return gaussian_convolve(data, float(self.sigma))


@register
class Convolution(Process):
    """Generic convolution by a configurable filter (box / gaussian / laplacian).

    Complements ``GaussianConvolution`` (native Rust kernel) with the usual scipy filters.
    The laplacian enhances edges (added back to the image), the others smooth.
    """

    process_id = "Convolution"
    category = "Convolution"
    parameters = [
        Parameter("filter", "enum", "gaussian",
                  choices=("gaussian", "box", "laplacian"), label=N_("Filter")),
        Parameter("radius", "real", 2.0, 0.1, 100.0, label=N_("Radius / sigma")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from scipy import ndimage

        r = float(self.radius)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            ch = data[:, :, c]
            if self.filter == "gaussian":
                out[:, :, c] = ndimage.gaussian_filter(ch, sigma=r)
            elif self.filter == "box":
                out[:, :, c] = ndimage.uniform_filter(ch, size=max(1, int(round(r))))
            else:  # laplacian: edge enhancement
                out[:, :, c] = ch + ndimage.gaussian_laplace(ch, sigma=r)
        return np.clip(out, 0.0, 1.0).astype(np.float32)
