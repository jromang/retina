"""CurvesTransformation — intensity transfer curve from control points.

Monotone cubic interpolation (PCHIP / Fritsch–Carlson): smooth and without overshoot,
suited to tone curves. No external dependency. ``points`` is a list of ``(x, y)`` pairs in
[0,1]. Default = identity.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


def _pchip(px: np.ndarray, py: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Cubic Hermite interpolation with monotone slopes (Fritsch–Carlson)."""
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    n = len(px)
    if n < 2:
        return np.clip(x, 0.0, 1.0)
    h = np.diff(px)
    delta = np.diff(py) / h
    d = np.zeros(n)
    d[0], d[-1] = delta[0], delta[-1]
    for k in range(1, n - 1):
        if delta[k - 1] * delta[k] <= 0:
            d[k] = 0.0
        else:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            d[k] = (w1 + w2) / (w1 / delta[k - 1] + w2 / delta[k])

    xc = np.clip(x, px[0], px[-1])
    idx = np.clip(np.searchsorted(px, xc) - 1, 0, n - 2)
    hs = h[idx]
    t = (xc - px[idx]) / hs
    h00 = (1 + 2 * t) * (1 - t) ** 2
    h10 = t * (1 - t) ** 2
    h01 = t**2 * (3 - 2 * t)
    h11 = t**2 * (t - 1)
    return h00 * py[idx] + h10 * hs * d[idx] + h01 * py[idx + 1] + h11 * hs * d[idx + 1]


@register
class CurvesTransformation(Process):
    process_id = "CurvesTransformation"
    category = "IntensityTransformations"
    parameters = [
        # list of control points (x, y) in [0,1]; default = identity
        Parameter("points", "points", default=[[0.0, 0.0], [1.0, 1.0]], label=N_("Points")),
        Parameter(
            "channel", "enum", default="RGB/K", choices=("RGB/K", "R", "G", "B"),
            label=N_("Channel"),
        ),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        pts = sorted((float(x), float(y)) for x, y in self.points)
        px = np.array([p[0] for p in pts], dtype=np.float64)
        py = np.array([p[1] for p in pts], dtype=np.float64)

        out = data.copy()
        chans = self._target_channels(data.shape[2])
        for c in chans:
            mapped = _pchip(px, py, data[:, :, c].ravel())
            out[:, :, c] = np.clip(mapped, 0.0, 1.0).reshape(data.shape[:2])
        return out.astype(np.float32)

    def _target_channels(self, n: int) -> list[int]:
        if self.channel == "RGB/K" or n == 1:
            return list(range(n))
        return [{"R": 0, "G": 1, "B": 2}[self.channel]] if n >= 3 else [0]
