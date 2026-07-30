"""Blink — sequence inspector: scrolling through raw frames to sort them by eye.

A blink panel scrolls through a stack of frames before any processing, to spot the ruined
exposures — a passing cloud, a satellite, tracking gone astray. It is a *sorting* gesture, not
a processing one: what is discarded here leaves the whole project.

# Lazy loading, and why it is not optional

An earlier version loaded **all** the frames into memory on open. On the most modest real data
set — fifteen 26 Mpx exposures — that already comes to 4.7 GB; over the hundred exposures of a
night it is untenable, and the gesture we want to make possible (looking at three images) would
pay the price of all the others.

Pixels are therefore read only on visit, and kept in a small LRU cache: a back-and-forth step
does not re-read the disk, but memory stays bounded whatever the length of the sequence. The
**statistics** follow the same rule — they require the pixels, so they are computed on visit
and memoized.

# Rejecting in Blink is not rejecting in the frame selector

Blink looks at raw frames, **before** any measurement: what it discards is a file that has no
business in the batch (wrong target, cloud, corrupt file). That is the job of
``retina.pipeline.exclude``, which removes it from the whole chain. The frame selector, by
contrast, judges **after** measurement and merely declines to stack the exposure — see
:mod:`retina.pipeline.selection`. Confusing the two would invalidate the calibration and
registration caches for a gesture that does not deserve it.
"""

from __future__ import annotations

import os
from collections import OrderedDict

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register

#: images kept in memory. Enough that a back-and-forth step re-reads nothing, few enough that
#: a sequence of a hundred 50 Mpx exposures stays openable.
CACHE_SIZE = 4


@register
class Blink(Process):
    process_id = "Blink"
    category = "ImageInspection"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Frame sequence")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.index = 0
        #: statistics per rank, computed on visit (``None`` until we have been there)
        self.stats: list[dict | None] = [None] * len(self.frames)
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()

    # --- sequence --------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.frames)

    def load(self) -> list[dict]:
        """Describes the sequence **without reading a single pixel**.

        What this list returns fits in the FITS header: name, geometry, exposure, filter.
        Enough to fill a navigation table in a fraction of a second over five hundred files —
        the statistics, for their part, come on visit (:meth:`stats_at`).
        """
        from ..io.fits import load_fits_header

        self.index = 0
        self.stats = [None] * len(self.frames)
        self._cache.clear()
        described = []
        for rank, path in enumerate(self.frames):
            entry: dict = {"index": rank, "frame": path,
                            "name": os.path.basename(path)}
            try:
                header = load_fits_header(path)
            except Exception:
                header = {}
            for key, mot in (("width", "NAXIS1"), ("height", "NAXIS2"),
                             ("exposure", "EXPTIME"), ("filter", "FILTER")):
                if mot in header:
                    entry[key] = header[mot]
            described.append(entry)
        return described

    def go_to(self, index: int) -> int:
        """Moves to a given rank, wrapping overflows around the sequence."""
        if not self.frames:
            return 0
        self.index = int(index) % len(self.frames)
        return self.index

    def step(self, delta: int = 1) -> int:
        return self.go_to(self.index + delta)

    # --- pixels and statistics, on demand --------------------------------------
    def array_at(self, index: int) -> np.ndarray | None:
        """Pixels of the frame at rank ``index``, through the LRU cache."""
        if not self.frames:
            return None
        index %= len(self.frames)
        cached = self._cache.get(index)
        if cached is not None:
            self._cache.move_to_end(index)
            return cached
        from ..io import load_image_array

        data = load_image_array(self.frames[index]).astype(np.float32)
        self._cache[index] = data
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return data

    def stats_at(self, index: int) -> dict:
        """Statistics of the visited frame, computed once then memoized."""
        if not self.frames:
            return {}
        index %= len(self.frames)
        known = self.stats[index]
        if known is not None:
            return known
        data = self.array_at(index)
        assert data is not None
        measure = {
            "index": index,
            "frame": self.frames[index],
            "name": os.path.basename(self.frames[index]),
            "median": float(np.median(data)),
            "min": float(data.min()),
            "max": float(data.max()),
            "shape": tuple(int(n) for n in data.shape),
        }
        self.stats[index] = measure
        return measure

    def current_image(self):
        """The current frame, as a :class:`~retina.model.image.Image`."""
        from ..model.image import Image

        data = self.array_at(self.index)
        return None if data is None else Image(data)

    def current_stats(self) -> dict:
        return self.stats_at(self.index)

    # --- display ---------------------------------------------------------------
    def show(self, app, window=None):
        """Displays the current frame — in **the same** window at every step.

        Replacing the pixel array of an existing window is enough to refresh everything: the
        pixel generation advances, the snapshot is rebuilt, the viewport reloads its texture.
        Opening one window per frame would leave a hundred of them behind, and a dedicated
        event channel would duplicate the one that already exists.
        """
        image = self.current_image()
        if image is None:
            return None
        target = window
        if target is None:
            target = app.new_window(image, window_id="Blink")
        else:
            target.main_view.set_image(image)
        return target

    def execute_global(self, app) -> bool:
        self.load()
        self.show(app)
        return True
