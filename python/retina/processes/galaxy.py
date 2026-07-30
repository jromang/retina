"""Galaxy isophote modeling (photutils.isophote).

``GalaxyModel`` fits concentric isophotal ellipses on a host galaxy then reconstructs a
smooth model — subtracted, it reveals the superimposed structures (spiral arms, globular
clusters, tidal features). Lazy import.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class GalaxyModel(Process):
    """Fits/subtracts a model of elliptical isophotes (photutils ``Ellipse``).

    The center ``(x0, y0)`` is in pixels; ``sma0`` = initial semi-major axis. With
    ``subtract=True`` the output is the residual (image − model), otherwise the smooth model
    itself. Falls back on the original image if the fit converges on no isophote at all.
    """

    process_id = "GalaxyModel"
    category = "MultiscaleProcessing"
    is_maskable = False
    parameters = [
        Parameter("x0", "int", -1, -1, 1_000_000, label=N_("Center X (-1 = middle)")),
        Parameter("y0", "int", -1, -1, 1_000_000, label=N_("Center Y (-1 = middle)")),
        Parameter("sma0", "real", 10.0, 1.0, 1000.0, label=N_("Initial semi-major axis")),
        Parameter("eps", "real", 0.2, 0.0, 0.95, label=N_("Initial ellipticity")),
        Parameter("subtract", "bool", True, label=N_("Subtract (otherwise: output the model)")),
    ]

    def _model_channel(self, ch: np.ndarray) -> np.ndarray | None:
        from photutils.isophote import Ellipse, EllipseGeometry, build_ellipse_model

        h, w = ch.shape
        x0 = w / 2.0 if self.x0 < 0 else float(self.x0)
        y0 = h / 2.0 if self.y0 < 0 else float(self.y0)
        geom = EllipseGeometry(x0=x0, y0=y0, sma=float(self.sma0),
                               eps=float(self.eps), pa=0.0)
        ellipse = Ellipse(ch.astype(np.float64), geometry=geom)
        isolist = ellipse.fit_image()
        if isolist is None or len(isolist) == 0:
            return None
        return build_ellipse_model(ch.shape, isolist).astype(np.float32)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            ch = data[:, :, c]
            try:
                model = self._model_channel(ch)
            except Exception:
                model = None
            if model is None:
                out[:, :, c] = ch
            elif self.subtract:
                out[:, :, c] = ch - model
            else:
                out[:, :, c] = model
        return np.clip(out, 0.0, 1.0).astype(np.float32)
