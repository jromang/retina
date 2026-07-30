"""Comets: LarsonSekanina (rotational gradient filter) and CometAlignment (global).

LarsonSekanina reveals the jets/structures of a coma by removing the centrally symmetric
component. CometAlignment stacks while following the linear motion of the nucleus.
scikit-image / scipy.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class LarsonSekanina(Process):
    """Rotational gradient filter: ``I − ½·(rot(+α) + rot(−α))`` about a center.

    Brings out asymmetric structures (cometary jets) by subtracting the mean of the versions
    rotated by ±α degrees. The default center is the center of the image.
    """

    process_id = "LarsonSekanina"
    category = "Convolution"
    parameters = [
        Parameter("angle", "real", 5.0, 0.1, 45.0, label=N_("Rotational angle (°)")),
        Parameter("cx", "real", -1.0, -1.0, 1_000_000.0, label=N_("Center X (-1 = middle)")),
        Parameter("cy", "real", -1.0, -1.0, 1_000_000.0, label=N_("Center Y (-1 = middle)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.transform import rotate

        h, w = data.shape[:2]
        center = (
            self.cx if self.cx >= 0 else (w - 1) / 2.0,
            self.cy if self.cy >= 0 else (h - 1) / 2.0,
        )
        a = float(self.angle)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            ch = data[:, :, c]
            plus = rotate(ch, a, center=center, order=1, mode="edge")
            minus = rotate(ch, -a, center=center, order=1, mode="edge")
            out[:, :, c] = ch - 0.5 * (plus + minus)
        return np.clip(out + 0.5, 0.0, 1.0).astype(np.float32)  # recenter around 0.5


@register
class CometAlignment(Process):
    """Stacks frames while following the linear motion of the cometary nucleus (global).

    Each frame ``i`` is shifted by ``(-i·vx, -i·vy)`` pixels then averaged → the comet stays
    sharp (the stars trail). ``vx/vy`` = velocity in pixels per frame.
    """

    process_id = "CometAlignment"
    category = "ImageRegistration"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Frames (time order)")),
        Parameter("vx", "real", 0.0, -1000.0, 1000.0, label=N_("X velocity (px/frame)")),
        Parameter("vy", "real", 0.0, -1000.0, 1000.0, label=N_("Y velocity (px/frame)")),
        Parameter("new_image_id", "str", "comet", label=N_("Result id")),
    ]

    def combine(self) -> np.ndarray:
        from scipy.ndimage import shift

        from ..io import load_image_array

        if not self.frames:
            raise ValueError(_t("CometAlignment: no frames provided"))
        acc = None
        for i, p in enumerate(self.frames):
            f = load_image_array(p).astype(np.float32)
            shifted = np.empty_like(f)
            for c in range(f.shape[2]):
                shifted[:, :, c] = shift(f[:, :, c], (-i * self.vy, -i * self.vx),
                                         order=1, mode="constant", cval=0.0)
            acc = shifted if acc is None else acc + shifted
        return (acc / len(self.frames)).astype(np.float32)

    def execute_global(self, app) -> bool:
        from ..model.image import Image

        app.new_window(Image(self.combine()), window_id=self.new_image_id or None)
        return True
