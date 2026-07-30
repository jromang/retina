"""Utilities: SampleFormatConversion, NewImage, ImageIdentifier, FITSHeader.

Small "technical" processes. The core (`Image`, `app`, `io`) already covers the essentials;
these processes expose them as replayable/scriptable operations.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class SampleFormatConversion(Process):
    """Quantizes the pixels to N bits (simulates an integer format), stays float32 inside."""

    process_id = "SampleFormatConversion"
    category = "Image"
    parameters = [
        Parameter("bits", "enum", "16", choices=("8", "16", "32"), label=N_("Bits per channel")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        bits = int(self.bits)
        if bits >= 32:
            return data.copy()
        levels = float((1 << bits) - 1)
        q = np.rint(np.clip(data, 0.0, 1.0) * levels) / levels
        return q.astype(np.float32)


@register
class NewImage(Process):
    """Creates a new image window (blank or filled) — global process."""

    process_id = "NewImage"
    category = "Image"
    is_global = True
    creates_window = True
    parameters = [
        Parameter("width", "int", 256, 1, 100_000, label=N_("Width")),
        Parameter("height", "int", 256, 1, 100_000, label=N_("Height")),
        Parameter("channels", "int", 1, 1, 4, label=N_("Channels")),
        Parameter("fill", "real", 0.0, 0.0, 1.0, label=N_("Fill value")),
        Parameter("new_image_id", "str", "new_image", label=N_("Result id")),
    ]

    def execute_global(self, app) -> bool:
        from ..model.image import Image

        arr = np.full((int(self.height), int(self.width), int(self.channels)),
                      float(self.fill), dtype=np.float32)
        app.new_window(Image(arr), window_id=self.new_image_id or None)
        return True


@register
class ImageIdentifier(Process):
    """Renames the target view/window (changes its identifier)."""

    process_id = "ImageIdentifier"
    category = "Image"
    is_maskable = False
    parameters = [Parameter("new_id", "str", "", label=N_("New identifier"))]

    def execute_on(self, view) -> bool:  # metadata: no pixel history entry
        if self.new_id:
            view.id = self.new_id
            if view.window is not None:
                view.window.id = self.new_id
        return True

    def execute_on_image(self, image):
        return image  # with no view, nothing to rename


@register
class FITSHeader(Process):
    """Writes a FITS keyword into the target window (``window.keywords``)."""

    process_id = "FITSHeader"
    category = "Image"
    is_maskable = False
    parameters = [
        Parameter("keyword", "str", "", label=N_("Keyword")),
        Parameter("value", "str", "", label=N_("Value")),
        Parameter("comment", "str", "", label=N_("Comment")),
    ]

    def execute_on(self, view) -> bool:
        if self.keyword and view.window is not None:
            view.window.keywords[self.keyword] = (
                (self.value, self.comment) if self.comment else self.value
            )
        return True

    def execute_on_image(self, image):
        return image  # the keywords live on the window, not on the bare Image
