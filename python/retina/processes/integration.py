"""Integration/stacking: combines several frames with robust rejection.

**Global** process: reads a list of files and creates a new window. Also used to build masters
(robust average of biases/darks/flats).

# Rejection, and why several of them are needed

No rejection algorithm suits every sample size, and that is the classic stacking trap: sigma
rejection, excellent on thirty exposures, is incapable of estimating a spread over four. Hence
five modes, plus an ``auto`` that chooses — the thresholds are the customary ones, drawn from
field experience and not from a derivation:

===============  ==========================================================
mode              when
===============  ==========================================================
``percentile``    fewer than 6 frames — deviation relative to the median,
                  without ever estimating a standard deviation
``winsorized``    6 to 15 frames, and all masters (bias/dark/flat) — the
                  spread is estimated on *clipped* values, hence insensitive
                  to the very outliers we are looking for
``linear_fit``    beyond 15 frames — fits a line to the sorted stack and
                  rejects whatever departs from it; tolerates an
                  illumination drift between exposures
``sigma``         the historical rejection, median + MAD
``none``          nothing
===============  ==========================================================

# Memory

A hundred 50 Mpx lights in float32 is 60 GB: stacking them all at once is not an option.
Integration therefore proceeds by **row bands**, sized by ``max_memory_mb``, and never
materializes more than one band at a time. The result is bit-for-bit identical to that of a
full stack — every rejection algorithm works pixel by pixel along the frame axis, never
between neighbors.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register

REJECTIONS = ("none", "auto", "sigma", "winsorized", "percentile", "linear_fit")

#: switching thresholds of ``auto``
AUTO_PERCENTILE_MAX = 5
AUTO_WINSORIZED_MAX = 15

#: correction factor of the winsorized standard deviation (Huber) — without it, clipping
#: underestimates the spread by about 5 %.
WINSOR_CORRECTION = 0.9473


def _median_sigma(stack: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Median and normalized MAD along the frame axis."""
    median = np.median(stack, axis=0, keepdims=True)
    mad = np.median(np.abs(stack - median), axis=0, keepdims=True)
    return median, mad * 1.4826


def _winsorized_sigma(stack: np.ndarray, iterations: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """Median and **winsorized** standard deviation: the spread estimated on clipped values.

    The idea is to measure the spread of the core of the distribution without the outliers
    contributing to it — which is exactly what an ordinary standard deviation cannot do, and
    the reason why an isolated cosmic ray can escape a sigma rejection.
    """
    median = np.median(stack, axis=0, keepdims=True)
    sigma = np.std(stack, axis=0, keepdims=True)
    for _ in range(iterations):
        bound = 1.5 * sigma
        ecrete = np.clip(stack, median - bound, median + bound)
        next_item = np.std(ecrete, axis=0, keepdims=True) / WINSOR_CORRECTION
        if np.all(np.abs(next_item - sigma) <= 1e-6 * np.maximum(sigma, 1e-12)):
            sigma = next_item
            break
        sigma = next_item
    return median, sigma


def _reject_sigma(stack: np.ndarray, low: float, high: float) -> np.ndarray:
    median, sigma = _median_sigma(stack)
    return _clip_mask(stack, median, sigma, low, high)


def _reject_winsorized(stack: np.ndarray, low: float, high: float) -> np.ndarray:
    median, sigma = _winsorized_sigma(stack)
    return _clip_mask(stack, median, sigma, low, high)


def _clip_mask(stack: np.ndarray, centre: np.ndarray, scale: np.ndarray,
               low: float, high: float) -> np.ndarray:
    # a null spread (constant stack) rejects nothing: without this guard, the division
    # would produce infinities and would discard perfectly healthy pixels
    sur = np.where(scale > 0, scale, np.inf)
    deviation = (stack - centre) / sur
    return (deviation < -low) | (deviation > high)


def _reject_percentile(stack: np.ndarray, low: float, high: float) -> np.ndarray:
    """**Relative** deviation from the median — the only rejection usable below six frames.

    It estimates no spread, so it cannot get it wrong by estimating it on three samples. In
    exchange, its thresholds are fractions of the signal, not sigmas.
    """
    median = np.median(stack, axis=0, keepdims=True)
    reference = np.maximum(np.abs(median), 1e-6)
    deviation = (stack - median) / reference
    return (deviation < -low) | (deviation > high)


def _reject_linear_fit(stack: np.ndarray, low: float, high: float) -> np.ndarray:
    """Fits a line to the **sorted** stack and rejects whatever departs from it.

    Over a large number of exposures, the values of a pixel sorted in increasing order line
    up: an illumination or transparency drift between exposures becomes a slope, which this
    rejection absorbs where a sigma rejection would take it for spread.
    """
    n = stack.shape[0]
    if n < 3:
        return np.zeros(stack.shape, dtype=bool)
    order = np.argsort(stack, axis=0)
    triees = np.take_along_axis(stack, order, axis=0)

    indices = np.arange(n, dtype=np.float32).reshape((n,) + (1,) * (stack.ndim - 1))
    i_moyen = float(indices.mean())
    y_moyen = triees.mean(axis=0, keepdims=True)
    variance = float(((indices - i_moyen) ** 2).sum())
    slope = ((indices - i_moyen) * (triees - y_moyen)).sum(axis=0, keepdims=True) / variance
    residuals = triees - (y_moyen + slope * (indices - i_moyen))

    scale = np.median(np.abs(residuals - np.median(residuals, axis=0, keepdims=True)),
                        axis=0, keepdims=True) * 1.4826
    sorted_mask = _clip_mask(residuals, np.zeros_like(scale), scale, low, high)
    # back to the original order: the mask must designate the same frames
    mask = np.empty_like(sorted_mask)
    np.put_along_axis(mask, order, sorted_mask, axis=0)
    return mask


def choose_rejection(count: int, kind: str = "light") -> str:
    """Rejection suited to the sample size.

    ``kind="master"`` forces the winsorized one: a master has few frames and a lot of fixed
    structure, which the rejection must under no circumstances mistake for aberrant signal.
    """
    if count < 3:
        return "none"  # below three samples, no rejection makes sense
    if count <= AUTO_PERCENTILE_MAX:
        return "percentile"
    if count <= AUTO_WINSORIZED_MAX or kind == "master":
        return "winsorized"
    return "linear_fit"


@register
class Integration(Process):
    process_id = "Integration"
    category = "ImageIntegration"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Frames")),
        Parameter("weights", "floatlist", [], label=N_("Weight per frame"),
                  tooltip=N_("Empty = uniform weights; otherwise one weight per frame")),
        Parameter("rejection", "enum", "auto", choices=REJECTIONS, label=N_("Rejection"),
                  tooltip=N_("auto: percentile below 6 frames, winsorized up to 15, "
                             "linear fit beyond")),
        Parameter("sigma_low", "real", 4.0, 0.0, 10.0, label=N_("Low sigma")),
        Parameter("sigma_high", "real", 3.0, 0.0, 10.0, label=N_("High sigma")),
        Parameter("percentile_low", "real", 0.2, 0.0, 1.0, label=N_("Low percentile")),
        Parameter("percentile_high", "real", 0.1, 0.0, 1.0, label=N_("High percentile")),
        Parameter("max_memory_mb", "real", 512.0, 16.0, 65536.0, label=N_("Max memory (MB)"),
                  tooltip=N_("Sizes the row bands; does not affect the result")),
        Parameter("new_image_id", "str", "integration", label=N_("Result id")),
    ]

    # --- rejection ------------------------------------------------------------
    #: frames discarded for not being readable, filled in by `combine()`
    skipped: list[tuple[str, str]] = []

    def effective_rejection(self, count: int) -> str:
        """Mode actually applied — ``auto`` resolved for this sample size."""
        if self.rejection != "auto":
            return self.rejection
        return choose_rejection(count)

    def _reject(self, stack: np.ndarray, mode: str) -> np.ndarray:
        if mode == "none":
            return np.zeros(stack.shape, dtype=bool)
        if mode == "percentile":
            return _reject_percentile(stack, self.percentile_low, self.percentile_high)
        if mode == "winsorized":
            return _reject_winsorized(stack, self.sigma_low, self.sigma_high)
        if mode == "linear_fit":
            return _reject_linear_fit(stack, self.sigma_low, self.sigma_high)
        return _reject_sigma(stack, self.sigma_low, self.sigma_high)

    # --- weights --------------------------------------------------------------
    def _weights_for_readable(self) -> np.ndarray | None:
        """Weights of the readable frames only — otherwise they would be off by one."""
        if not self.weights or not self.skipped:
            return self._weights(len(self.frames) - len(self.skipped))
        lost = {path for path, _ in self.skipped}
        kept_items = [w for path, w in zip(self.frames, self.weights, strict=True)
                  if path not in lost]
        original, self.weights = self.weights, kept_items
        try:
            return self._weights(len(kept_items))
        finally:
            self.weights = original

    def _weights(self, count: int) -> np.ndarray | None:
        """Normalized weights, or ``None`` if the integration is uniform."""
        if not self.weights:
            return None
        if len(self.weights) != count:
            raise ValueError(
                _t("Integration: {n} weights for {count} frames").format(
                    n=len(self.weights), count=count))
        weights = np.asarray(self.weights, dtype=np.float32)
        if np.any(weights < 0.0):
            raise ValueError(_t("Integration: negative weight"))
        total = float(weights.sum())
        if total <= 0.0:
            raise ValueError(_t("Integration: all weights are zero"))
        return weights / total

    # --- combination ----------------------------------------------------------
    def _band_rows(self, height: int, width: int, channels: int, count: int) -> int:
        """Band height fitting within the memory budget, at least one row."""
        by_line = count * width * channels * 4  # float32
        budget = float(self.max_memory_mb) * 1024 * 1024
        # No floor: the announced budget is the applied budget. A single row remains the
        # absolute minimum — we cannot integrate half a row.
        return max(1, min(height, int(budget // max(by_line, 1))))

    def combine(self) -> np.ndarray:
        from ..io.lazy import open_lazy

        if not self.frames:
            raise ValueError(_t("Integration: no frames provided"))
        # One unreadable file among thirty does not cancel the other twenty-nine: we
        # discard it and we say so. This is the usual behavior of an integration
        # (`onError = Continue`), and the only reasonable one on a whole night's batch.
        readers, self.skipped = [], []
        for path in self.frames:
            try:
                readers.append(open_lazy(path))
            except Exception as exc:
                self.skipped.append((path, f"{type(exc).__name__}: {exc}"))
        if not readers:
            raise ValueError(_t("Integration: no readable frames"))
        try:
            shapes = {reader.shape for reader in readers}
            if len(shapes) != 1:
                raise ValueError(
                    _t("Integration: heterogeneous geometries {shapes}").format(
                        shapes=sorted(shapes)))
            height, width, channels = readers[0].shape
            count = len(readers)
            mode = self.effective_rejection(count)
            wmap = self._weights_for_readable()
            if wmap is not None:
                wmap = wmap.reshape(-1, 1, 1, 1)

            band_height = self._band_rows(height, width, channels, count)
            output = np.empty((height, width, channels), dtype=np.float32)
            for start in range(0, height, band_height):
                fin = min(start + band_height, height)
                # One report per frame AND per band: on a small stack there is only one
                # band, and without that level cancellation would have no purchase at all.
                lues = []
                for index, reader in enumerate(readers):
                    self._progress((start + (fin - start) * index / count) / height,
                                   f"Reading {index + 1}/{count} — rows {start}–{fin}")
                    lues.append(reader.band(start, fin))
                self._progress(fin / height,
                               f"Integration ({mode}) — rows {start}–{fin}/{height}")
                output[start:fin] = self._combine_band(np.stack(lues, axis=0), mode, wmap)
                del lues
            self._progress(1.0, _t("Integration"))
            return output
        finally:
            for reader in readers:
                reader.close()

    def _combine_band(self, stack: np.ndarray, mode: str,
                      wmap: np.ndarray | None) -> np.ndarray:
        rejete = self._reject(stack, mode)
        kept = (~rejete).astype(np.float32)
        if wmap is not None:
            kept = kept * wmap
        # The total weight varies from one pixel to the next (rejection does not discard the
        # same frames everywhere): we renormalize pixel by pixel.
        total = kept.sum(axis=0)
        somme = (stack * kept).sum(axis=0)
        raw_data = self._mean(stack, wmap)  # fallback where everything has been rejected
        return np.where(total > 0, somme / np.where(total > 0, total, 1.0),
                        raw_data).astype(np.float32)

    @staticmethod
    def _mean(stack: np.ndarray, wmap: np.ndarray | None) -> np.ndarray:
        return stack.mean(axis=0) if wmap is None else (stack * wmap).sum(axis=0)

    def execute_global(self, app) -> bool:
        from ..model.image import Image

        app.new_window(Image(self.combine()), window_id=self.new_image_id or None)
        return True
