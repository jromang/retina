"""Statistics — reads robust estimators (astropy.stats), without modifying the image."""

from __future__ import annotations

import numpy as np

from ..process.base import Process
from ..process.registry import register


@register
class Statistics(Process):
    process_id = "Statistics"
    category = "Image"
    parameters = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    def measure(self, image) -> dict:
        from astropy.stats import biweight_location, mad_std

        d = image.data if hasattr(image, "data") else np.asarray(image)
        per_channel = {}
        for c in range(d.shape[2]):
            ch = d[:, :, c]
            per_channel[c] = {
                "mean": float(np.mean(ch)),
                "median": float(np.median(ch)),
                "mad_std": float(mad_std(ch)),
                "biweight": float(biweight_location(ch)),
                "min": float(np.min(ch)),
                "max": float(np.max(ch)),
            }
        return {"channels": per_channel}

    def execute_on(self, view) -> bool:  # read-only: no history entry
        self.result = self.measure(view.image)
        return True

    def execute_on_image(self, image):
        self.result = self.measure(image)
        return image
