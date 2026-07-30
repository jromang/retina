"""Component separation (scikit-learn) — channel decorrelation.

``ComponentSeparation`` treats the channels as mixed signals and extracts independent (ICA)
or decorrelated (PCA) components from them. Astro uses: removing a correlated gradient
present on every channel, separating a continuum from a narrowband line, decomposing an
LRGB combination. Lazy import of ``sklearn``.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class ComponentSeparation(Process):
    """Decomposes the channels into PCA/ICA components (one pixel = one sample).

    Each pixel is a vector of ``C`` channels; PCA/ICA estimates a basis of ``C`` components.
    The output replaces the channels with the components (normalized to [0,1]) — the 1st PCA
    component captures the common signal (correlated gradient/luminance), the following ones
    the decorrelated residuals. Requires ≥2 channels.
    """

    process_id = "ComponentSeparation"
    category = "ColorCalibration"
    is_maskable = False  # may reorder/re-sign the channels
    parameters = [
        Parameter("method", "enum", "pca", choices=("pca", "ica"), label=N_("Method")),
        Parameter("whiten", "bool", True, label=N_("Whitening (PCA)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 2:
            return data.copy()
        from sklearn.decomposition import PCA, FastICA

        h, w, c = data.shape
        x = data.reshape(-1, c).astype(np.float64)
        if self.method == "ica":
            model = FastICA(n_components=c, whiten="unit-variance", max_iter=500, random_state=0)
        else:
            model = PCA(n_components=c, whiten=bool(self.whiten))
        comps = model.fit_transform(x)  # (N, C)
        comps = comps.reshape(h, w, c)
        # normalize each component to [0,1] for display/chaining
        out = np.empty_like(data)
        for i in range(c):
            band = comps[:, :, i]
            lo, hi = float(band.min()), float(band.max())
            out[:, :, i] = (band - lo) / (hi - lo) if hi > lo else 0.0
        return out.astype(np.float32)
