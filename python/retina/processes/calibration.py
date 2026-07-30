"""Calibration: bias/dark subtraction + flat correction (masters given as files).

Pragmatic version by array arithmetic (no ccdproc unit bookkeeping): sufficient for M2; we can
switch over to ``ccdproc.ccd_process`` if need be. Single-image: applies to the active view,
masters supplied by path.

    calibrated = (raw − bias − k·dark) / (flat / mean(flat)) + pedestal

Two parameters deserve an explanation, because they decide the correctness of the result and
because neither of them has an "obvious" value:

**``dark_optimize``** — rather than trusting the ratio of exposure times, we can *search* for
the factor that removes the dark best. The criterion is not obvious: fitting the dark to the
signal by least squares would give a factor dominated by the sky, which has nothing to do with
dark current. What we minimize is the **residual pixel-to-pixel grain** — the fixed-pattern
noise, precisely what the dark carries and the sky does not. The optimal factor is therefore
the one that makes the image smoothest at pixel scale, and it is searched for by golden section
over a bounded interval.

This is what makes a dark of a different exposure time genuinely usable, where ``dark_scale``
alone assumes that dark current is perfectly linear in time — which it only approximately is.

**``dark_scale`` (k)** — a master dark contains the bias. As long as its exposure equals that
of the raw frame, we supply *only* it: subtracting it also removes the bias. As soon as it has
to be scaled (different exposure), multiplying the dark would also multiply its bias, which
does not depend on exposure time; one must then supply the bias **and** a previously
bias-subtracted dark — a "dark current" frame. It is :mod:`retina.pipeline.groups` that decides
between the two arrangements and computes ``k``; here we apply the formula.

**``flat_clipping``** — a flat pixel far below the mean level does not call for a very strong
correction: it saw nothing. Dividing by it would amplify its noise without limit. The threshold
(5 % of the mean flat, a customary value) marks the boundary between "correct" and "leave
alone".

**``pedestal``** — after subtraction, the sky background oscillates around zero and half the
noise falls below 0. Truncating it destroys information (fatal in narrowband, where the signal
is close to the background) and biases rejection at integration. The ``auto`` mode therefore
lifts the image just enough for the fraction of negative pixels to fall back below
``pedestal_limit``, before the final clip.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def _pixel_grain(image: np.ndarray) -> float:
    """**Pixel-to-pixel** spread — the grain, not the contrast of the image.

    We measure the difference between immediate neighbors, in both directions, with a robust
    estimator: the astronomical signal varies slowly from one pixel to the next, the
    fixed-pattern noise of a dark does not, and that is the whole point of this criterion. A MAD
    rather than a standard deviation, otherwise a saturated star would dominate the measurement.
    """
    if image.ndim == 3:
        image = image.mean(axis=2)
    deviations = np.concatenate([np.diff(image, axis=0).ravel(),
                             np.diff(image, axis=1).ravel()])
    return float(np.median(np.abs(deviations - np.median(deviations))))


def optimize_dark_scale(light: np.ndarray, dark: np.ndarray, initial: float = 1.0,
                        amplitude: float = 2.0, iterations: int = 24) -> float:
    """Factor ``k`` minimizing the grain of ``light − k·dark``.

    Search by **golden section** between ``initial/amplitude`` and ``initial×amplitude``: the
    criterion is unimodal (too little dark leaves the pattern, too much reintroduces one of
    opposite sign), and twenty-four iterations are enough to locate it to better than 1 %.

    ``dark`` must be **bias-subtracted**: optimizing a dark that still contains its bias would
    amount to scaling the pedestal, which no factor can do well.
    """
    if dark.shape != light.shape:
        raise ValueError(_t("optimize_dark_scale: geometry mismatch"))
    bottom = max(initial / amplitude, 0.0)
    top = initial * amplitude
    if top <= bottom:
        return initial

    ratio = (np.sqrt(5.0) - 1.0) / 2.0  # golden section
    x1, x2 = top - ratio * (top - bottom), bottom + ratio * (top - bottom)
    f1, f2 = _pixel_grain(light - x1 * dark), _pixel_grain(light - x2 * dark)
    for _ in range(iterations):
        if f1 < f2:
            top, x2, f2 = x2, x1, f1
            x1 = top - ratio * (top - bottom)
            f1 = _pixel_grain(light - x1 * dark)
        else:
            bottom, x1, f1 = x1, x2, f2
            x2 = bottom + ratio * (top - bottom)
            f2 = _pixel_grain(light - x2 * dark)
    return float((bottom + top) / 2.0)


@register
class ImageCalibration(Process):
    process_id = "ImageCalibration"
    category = "Calibration"
    supports_realtime = False  # masters of fixed size
    parameters = [
        Parameter("master_bias", "path", "", label=N_("Master bias")),
        Parameter("master_dark", "path", "", label=N_("Master dark")),
        Parameter("master_flat", "path", "", label=N_("Master flat")),
        Parameter("dark_scale", "real", 1.0, 0.0, 10.0, label=N_("Dark scale"),
                  tooltip=N_("≠ 1 requires a bias-subtracted dark (dark current) AND the "
                             "master bias")),
        Parameter("dark_optimize", "bool", False, label=N_("Optimize dark scale"),
                  tooltip=N_("Searches for the factor minimizing residual grain; only "
                             "meaningful on a bias-subtracted dark")),
        Parameter("dark_optimize_range", "real", 2.0, 1.1, 10.0,
                  label=N_("Search range"),
                  tooltip=N_("The factor is searched between scale/range and scale×range")),
        Parameter("pedestal_mode", "enum", "auto", choices=("none", "auto", "manual"),
                  label=N_("Pedestal")),
        Parameter("pedestal", "real", 0.0, 0.0, 1.0, label=N_("Manual pedestal")),
        Parameter("pedestal_limit", "real", 1e-4, 0.0, 1.0,
                  label=N_("Tolerated negative fraction")),
        Parameter("flat_clipping", "real", 0.05, 0.0, 1.0, label=N_("Valid flat threshold"),
                  tooltip=N_("Fraction of the mean flat below which a pixel is considered "
                             "blind and is not divided")),
    ]

    def _auto_pedestal(self, out: np.ndarray) -> float:
        """Minimal lift so that the share of negative pixels falls below the limit.

        The quantile is taken on the **body** of the distribution, excluding aberrant values.
        Without that, a handful of pathological pixels — a sensor always has a few dead
        columns — dictates the pedestal of the whole image: it would be shifted by several
        hundred times the sky background to save one ten-thousandth of the pixels. Distorting
        100 % of the image for 0.01 % is never the right trade-off.
        """
        if not np.any(out < 0.0):
            return 0.0
        limit = float(self.pedestal_limit)
        median = float(np.median(out))
        dispersion = float(np.median(np.abs(out - median))) * 1.4826
        if dispersion <= 0.0:
            return max(0.0, -float(out.min()))
        body = out[np.abs(out - median) <= 10.0 * dispersion]
        if body.size == 0:
            return 0.0
        if limit <= 0.0:
            return max(0.0, -float(body.min()))
        return max(0.0, -float(np.quantile(body, limit)))

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from ..io import load_image_array

        out = data.astype(np.float32).copy()
        if self.master_bias:
            self._progress(0.0, _t("Subtracting bias"))
            out -= load_image_array(self.master_bias)
        if self.master_dark:
            dark = load_image_array(self.master_dark)
            scale = float(self.dark_scale)
            if self.dark_optimize:
                self._progress(0.2, _t("Optimizing dark scale"))
                scale = optimize_dark_scale(out, dark, scale,
                                              float(self.dark_optimize_range))
                #: last factor retained — the pipeline logs it
                self.optimized_scale = scale
            self._progress(0.33, _t("Subtracting dark (×{scale:.3f})").format(scale=scale))
            out -= scale * dark
        if self.master_flat:
            self._progress(0.66, _t("Flat correction"))
            flat = load_image_array(self.master_flat).astype(np.float32)
            flat = flat / max(float(np.mean(flat)), 1e-6)
            # A very low flat pixel is not a strong correction: it is a pixel that saw
            # nothing — dead column, mask, unilluminated overscan area. Dividing by 1e-6
            # there would multiply the noise by a million, and those few pixels would then
            # dominate every statistic drawn from the image. We therefore leave them as they
            # are rather than making them blow up.
            threshold = float(self.flat_clipping)
            valid = flat >= threshold
            out = out / np.where(valid, flat, 1.0)

        if self.pedestal_mode == "manual":
            out += float(self.pedestal)
        elif self.pedestal_mode == "auto":
            out += self._auto_pedestal(out)
        return np.clip(out, 0.0, 1.0).astype(np.float32)
