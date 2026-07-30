"""``stats.*`` family — histograms and statistics computed on the server side.

# Why not on the client side

The frontend has the pixels, in float16. It could build its histogram itself. Two reasons not
to:

- **precision**: the domain's robust statistics (median, MADN) run on the float32, and a
  histogram computed on degraded data would not match the STF values displayed next to it;
- **volume**: on a 6000×4000×3 view, walking 72 million pixels in JavaScript blocks the
  interface thread. numpy does it in a worker thread without freezing anything.

The result is cached by pixel generation: replaying the histogram after a mere STF change
recomputes nothing, since the STF does not touch the pixels.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import Executor
from typing import TYPE_CHECKING

import numpy as np

from .rpc import DOMAIN_ERROR, RpcError

if TYPE_CHECKING:
    from ..app import Application
    from .state import SnapshotBuilder

STATS_METHODS: dict[str, bool] = {
    "stats.histogram": False,
}

#: Default resolution. 256 is enough to draw a curve: beyond that, we transmit noise.
DEFAULT_BINS = 256
MAX_BINS = 4096
#: Enough for the active view and a few previews; the entries are tiny.
CACHE_SIZE = 8


class StatsHandlers:
    def __init__(
        self, app: Application, snapshots: SnapshotBuilder, executor: Executor
    ) -> None:
        self._app = app
        self._snapshots = snapshots
        self._executor = executor
        self._cache: OrderedDict[tuple[str, int, int], dict] = OrderedDict()

    async def histogram(self, view: str, bins: int = DEFAULT_BINS) -> dict:
        """Per-channel histogram of the view, plus its robust statistics.

        The counts are returned **raw**: it is up to the client to decide its scale (the STF
        panel displays them in log, without which the sky background swamps everything else).
        """
        if not 2 <= bins <= MAX_BINS:
            raise RpcError(DOMAIN_ERROR, f"bins out of range: {bins} (2..{MAX_BINS})")
        try:
            target = self._app.view(view)
        except KeyError:
            raise RpcError(DOMAIN_ERROR, f"unknown view: {view!r}") from None

        generation = self._snapshots.pixel_gen(view) or 0
        key = (view, generation, bins)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self._executor, _compute, target.image, bins
        )
        self._cache[key] = result
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return result


def _compute(image, bins: int) -> dict:
    data = np.asarray(image.data, dtype=np.float32)
    if data.ndim == 2:
        data = data[:, :, np.newaxis]

    channels = []
    for index in range(data.shape[2]):
        plane = data[:, :, index]
        counts, _edges = np.histogram(plane, bins=bins, range=(0.0, 1.0))
        channels.append(
            {
                "counts": counts.astype(np.int64).tolist(),
                "median": float(image.median(index)),
                "madn": float(image.madn(index)),
                "min": float(plane.min()),
                "max": float(plane.max()),
            }
        )
    return {"bins": bins, "range": [0.0, 1.0], "channels": channels}
