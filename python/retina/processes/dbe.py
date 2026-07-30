"""DynamicBackgroundExtraction — background extraction from sample points.

DBE style: the user places points where the image is "background" (no star/nebula); the
robust local background is measured at each point, a smooth surface is fitted (thin-plate
RBF or polynomial), and it is subtracted (or divided out). Much more powerful than the
automatic Background2D on complex gradients.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def _poly_surface(px, py, v, degree, xx, yy, w, h):
    """Fits a 2D polynomial (normalized coords) and evaluates it on the grid."""
    def terms(x, y):
        return np.column_stack(
            [x**i * y**j for i in range(degree + 1) for j in range(degree + 1 - i)]
        )

    A = terms(px / max(w - 1, 1), py / max(h - 1, 1))
    coef, *_ = np.linalg.lstsq(A, v, rcond=None)
    grid = terms(xx.ravel() / max(w - 1, 1), yy.ravel() / max(h - 1, 1))
    return (grid @ coef).reshape(xx.shape)


@register
class DynamicBackgroundExtraction(Process):
    process_id = "DynamicBackgroundExtraction"
    category = "BackgroundModelization"
    parameters = [
        Parameter("samples", "pointlist", default=[], label=N_("Points (x, y)")),
        Parameter("sample_radius", "int", 15, 2, 200, label=N_("Sample radius (px)")),
        Parameter("tolerance", "real", 3.0, 0.1, 20.0, label=N_("σ tolerance (star rejection)")),
        Parameter("model", "enum", "rbf", choices=("rbf", "poly"), label=N_("Model")),
        Parameter("degree", "int", 2, 1, 6, label=N_("Degree (poly)")),
        Parameter("smoothing", "real", 0.0, 0.0, 100.0, label=N_("Smoothing (rbf)")),
        Parameter("subtract", "bool", True, label=N_("Subtract (otherwise: model)")),
        Parameter("pedestal", "real", 0.1, 0.0, 1.0, label=N_("Pedestal")),
    ]

    def _measure(self, data: np.ndarray):
        """Robust local background (sigma-clipped median) measured at each point, per channel."""
        h, w, nch = data.shape
        r = int(self.sample_radius)
        pts, vals = [], [[] for _ in range(nch)]
        for (x, y) in self.samples:
            xi, yi = int(round(x)), int(round(y))
            if not (0 <= xi < w and 0 <= yi < h):
                continue
            x0, x1 = max(0, xi - r), min(w, xi + r + 1)
            y0, y1 = max(0, yi - r), min(h, yi + r + 1)
            patch = data[y0:y1, x0:x1, :]
            pts.append((xi, yi))
            for c in range(nch):
                p = patch[:, :, c].ravel()
                med = float(np.median(p))
                madn = float(np.median(np.abs(p - med))) * 1.4826 + 1e-6
                keep = p[np.abs(p - med) < self.tolerance * madn]  # discards the stars
                vals[c].append(float(np.median(keep) if keep.size else med))
        return np.array(pts, dtype=float), [np.array(v) for v in vals]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if len(self.samples) < 3:
            raise ValueError(_t("DBE: at least 3 sample points required."))
        h, w, nch = data.shape
        pts, vals = self._measure(data)
        if len(pts) < 3:
            raise ValueError(_t("DBE: too few valid points (inside the frame)."))

        yy, xx = np.mgrid[0:h, 0:w]
        model = np.empty((h, w, nch), dtype=np.float32)
        for c in range(nch):
            self._progress(c / nch, _t("Background model — channel {n}/{total}").format(
                n=c + 1, total=nch))
            if self.model == "rbf":
                from scipy.interpolate import RBFInterpolator

                rbf = RBFInterpolator(pts, vals[c], kernel="thin_plate_spline",
                                      smoothing=self.smoothing)
                grid = np.column_stack([xx.ravel(), yy.ravel()]).astype(float)
                model[:, :, c] = rbf(grid).reshape(h, w)
            else:
                model[:, :, c] = _poly_surface(pts[:, 0], pts[:, 1], vals[c],
                                               int(self.degree), xx, yy, w, h)

        out = (data - model + self.pedestal) if self.subtract else model
        return np.clip(out, 0.0, 1.0).astype(np.float32)
