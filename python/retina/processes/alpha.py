"""Alpha channels — creation, extraction, removal.

The ``(H, W, C)`` model carries the alpha as an extra channel beyond the nominal channels
(convention: C = 2 → gray+alpha, C = 4 → RGBA — see ``Image.nominal_channels``). These two
processes are the entry points for "CreateAlphaChannels / ExtractAlphaChannels"; the PNG
export (``io/raster.py``) honors the alpha, and the viewport composites it according to
``TransparencyMode`` (checkerboard, solid color or viewport background —
``web/src/viewport/shaders.ts``).
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register

_LUMA = (0.2126, 0.7152, 0.0722)


def _nominal(data: np.ndarray) -> int:
    return 1 if data.shape[2] <= 2 else 3


def _has_alpha(data: np.ndarray) -> bool:
    return data.shape[2] > _nominal(data)


@register
class CreateAlphaChannels(Process):
    """Adds (or replaces) the alpha channel: constant, luminance, or another view."""

    process_id = "CreateAlphaChannels"
    category = "ColorSpaces"
    is_maskable = False  # blending the creation of an alpha through a mask makes no sense

    parameters = [
        Parameter("mode", "enum", "constant", choices=("constant", "luminance", "view"),
                  label=N_("Alpha source")),
        Parameter("value", "real", 1.0, 0.0, 1.0, label=N_("Constant value")),
        Parameter("view_id", "str", "", label=N_("Source view")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        nominal = data[:, :, : _nominal(data)]
        if self.mode == "constant":
            alpha = np.full(data.shape[:2], float(self.value), dtype=np.float32)
        elif self.mode == "luminance":
            if nominal.shape[2] == 1:
                alpha = nominal[:, :, 0]
            else:
                alpha = sum(w * nominal[:, :, i] for i, w in enumerate(_LUMA))
        else:  # view
            from ..process import context

            arr = context.resolve_image_full(self.view_id) if self.view_id else None
            if arr is None:
                raise ValueError(
                    _t("Source view not found: {view_id!r}").format(view_id=self.view_id))
            if arr.shape[:2] != data.shape[:2]:
                raise ValueError(
                    _t("Incompatible geometry: {width}×{height} for a "
                       "{img_width}×{img_height} image").format(
                        width=arr.shape[1], height=arr.shape[0],
                        img_width=data.shape[1], img_height=data.shape[0])
                )
            alpha = arr[:, :, 0]
        return np.dstack([nominal, np.clip(alpha, 0.0, 1.0)]).astype(np.float32)


@register
class ExtractAlphaChannels(Process):
    """Extracts the alpha into a new grayscale window, or removes it from the image.

    ``extract`` produces a new window (the source image is left intact); ``remove``
    transforms the view — ordinary history and undo. Two gestures, one process: that is the
    conventional split.
    """

    process_id = "ExtractAlphaChannels"
    category = "ColorSpaces"
    is_maskable = False

    parameters = [
        Parameter("mode", "enum", "extract", choices=("extract", "remove"), label=N_("Mode")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # `app.apply` reads `creates_window` on the INSTANCE: extracting opens a window,
        # removing modifies the view in place.
        self.creates_window = self.mode == "extract"

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if not _has_alpha(data):
            raise ValueError(_t("The image has no alpha channel."))
        if self.mode == "extract":
            return np.ascontiguousarray(data[:, :, _nominal(data):_nominal(data) + 1])
        return np.ascontiguousarray(data[:, :, : _nominal(data)])
