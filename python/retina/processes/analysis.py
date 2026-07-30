"""Inspection processes — optical quality of the field.

The usual family of field analysis tools, taken up here as **measurement processes** rather
than as a script engine: they transform nothing, they fill ``.result``, and the interface does
with it what it wants.

Nothing that already exists is reimplemented: star shape comes from
:func:`~retina.processes.psf.fit_psf_stars`, the fitter shared with ``DynamicPSF`` and
``SubframeSelector``. What these processes bring is the **partitioning of the field** — because
the question is not "what is the FWHM" but "where is it bad".
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register
from .psf import fit_psf_stars
from .stars import detect_sources

#: tag of the overlays laid down by :class:`FWHMEccentricity`
FIELD_MAP_TAG = "fwhm-map"


def _luminance(data: np.ndarray) -> np.ndarray:
    return (data.mean(axis=2) if data.shape[2] > 1 else data[:, :, 0]).astype(np.float64)


@register
class FWHMEccentricity(Process):
    """Map of the field's FWHM and eccentricity — focus and collimation, seen.

    A median FWHM does not say much: an image can be excellent at the center and soft in a
    corner, and that is precisely what we want to know. The field is therefore cut into
    ``grid`` × ``grid`` cells, and each cell returns the median of its stars.

    Eccentricity is even more telling than FWHM: it betrays tracking (elongation in a common
    direction) and sensor tilt (**radial** elongation, growing towards the edges). Hence the
    ellipses drawn at the measured orientation — a map of numbers would not show the direction.

    Read-only; result in ``.result``.
    """

    process_id = "FWHMEccentricity"
    category = "ImageInspection"
    supports_realtime = False
    parameters = [
        Parameter("fwhm", "real", 3.0, 1.0, 20.0, label=N_("Detection FWHM")),
        Parameter("threshold_sigma", "real", 5.0, 1.0, 50.0, label=N_("Threshold (σ)")),
        Parameter("max_stars", "int", 300, 10, 5000, label=N_("Fitted stars (max)")),
        Parameter("grid", "int", 5, 1, 16, label=N_("Field grid (n×n)")),
        Parameter("psf_model", "enum", "gaussian", choices=("gaussian", "moffat"),
                  label=N_("PSF profile")),
        Parameter("show_map", "bool", True, label=N_("Draw field map")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    def measure(self, image) -> dict:
        from astropy.stats import sigma_clipped_stats

        data = image.data if hasattr(image, "data") else np.asarray(image)
        lum = _luminance(data)
        height, width = lum.shape
        sources = detect_sources(lum, self.fwhm, self.threshold_sigma)
        if sources is None or not len(sources):
            self.result = {"n_stars": 0, "fwhm": None, "eccentricity": None,
                           "stars": [], "cells": []}
            return self.result

        # The brightest first: with a bounded number of fits, they are the ones whose shape is
        # the best constrained.
        sources.sort("flux")
        sources.reverse()
        xcol = "xcentroid" if "xcentroid" in sources.colnames else "x_centroid"
        ycol = "ycentroid" if "ycentroid" in sources.colnames else "y_centroid"
        _, background, _ = sigma_clipped_stats(lum, sigma=3.0)
        stars = fit_psf_stars(lum, list(sources[xcol]), list(sources[ycol]),
                                fwhm_guess=float(self.fwhm), background=float(background),
                                limit=int(self.max_stars), function=self.psf_model)

        self.result = {
            "n_stars": len(stars),
            "fwhm": float(np.median([e["fwhm"] for e in stars])) if stars else None,
            "eccentricity": (float(np.median([e["eccentricity"] for e in stars]))
                             if stars else None),
            "stars": stars,
            "cells": self._cells(stars, height, width),
            "width": width,
            "height": height,
        }
        return self.result

    def _cells(self, stars: list[dict], height: int, width: int) -> list[dict]:
        """Median per field cell. An empty cell is returned all the same, empty.

        Returning it rather than omitting it is what allows the interface to draw a complete
        grid: a hole in the map is information ("no fittable star here"), not a cell to make
        disappear.
        """
        n = max(int(self.grid), 1)
        cells = []
        for line in range(n):
            for column in range(n):
                x0, x1 = column * width / n, (column + 1) * width / n
                y0, y1 = line * height / n, (line + 1) * height / n
                inside = [e for e in stars if x0 <= e["x"] < x1 and y0 <= e["y"] < y1]
                cells.append({
                    "row": line, "col": column,
                    "x": 0.5 * (x0 + x1), "y": 0.5 * (y0 + y1),
                    "n_stars": len(inside),
                    "fwhm": float(np.median([e["fwhm"] for e in inside])) if inside else None,
                    "fwhm_x": (float(np.median([e["fwhm_x"] for e in inside]))
                               if inside else None),
                    "fwhm_y": (float(np.median([e["fwhm_y"] for e in inside]))
                               if inside else None),
                    "eccentricity": (float(np.median([e["eccentricity"] for e in inside]))
                                     if inside else None),
                    "theta": (float(np.median([e["theta"] for e in inside]))
                              if inside else None),
                })
        return cells

    def overlays(self) -> list[dict]:
        """Ellipses and labels of the field map, in image coordinates.

        The ellipses are **enlarged** by a common factor: at real scale, a FWHM of three pixels
        on a six-thousand-pixel image is invisible. What matters here is the comparison between
        cells, not the absolute size — which is written next to them.
        """
        if not self.result:
            return []
        cells = [c for c in self.result["cells"] if c["fwhm"]]
        if not cells:
            return []
        n = max(int(self.grid), 1)
        scale = min(self.result["width"], self.result["height"]) / (n * 6.0)
        reference = float(np.median([c["fwhm"] for c in cells]))
        factor = scale / max(reference, 1e-6)
        return [
            {"kind": "ellipses", "color": (1.0, 0.85, 0.2, 0.9), "width": 1.5,
             "items": [{"x": c["x"], "y": c["y"],
                        "rx": 0.5 * c["fwhm_x"] * factor, "ry": 0.5 * c["fwhm_y"] * factor,
                        "theta": c["theta"] or 0.0} for c in cells]},
            {"kind": "text", "color": (1.0, 0.85, 0.2, 0.9), "size": 12,
             "items": [{"x": c["x"], "y": c["y"] + scale * 0.9,
                        "text": f"{c['fwhm']:.2f} / {c['eccentricity']:.2f}"}
                       for c in cells]},
        ]

    def execute_on(self, view) -> bool:  # read-only
        self.measure(view.image)
        window = view.window
        if self.show_map and window is not None:
            window.viewport.set_overlays(FIELD_MAP_TAG, self.overlays())
        return True

    def execute_on_image(self, image):
        self.measure(image)
        return image


@register
class AberrationInspector(Process):
    """n×n mosaic of the corners, the edges and the center — aberrations side by side.

    The gesture is dumb and that is its strength: comparing the four corners of a fifty-megapixel
    image otherwise takes four zoom round-trips, during which the eye forgets what it has just
    seen. Putting them side by side makes coma, tilt and field curvature immediately readable.

    Produces a **new window**; the original image is not touched.
    """

    process_id = "AberrationInspector"
    category = "ImageInspection"
    creates_window = True
    is_maskable = False
    parameters = [
        Parameter("mosaic_size", "int", 3, 2, 9, label=N_("Mosaic size (n×n)")),
        Parameter("panel_size", "int", 256, 32, 2048, label=N_("Panel size (px)")),
        Parameter("separation", "int", 4, 0, 64, label=N_("Separation (px)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        n = max(int(self.mosaic_size), 2)
        side = int(self.panel_size)
        marge = int(self.separation)
        height, width, channels = data.shape
        # A thumbnail larger than the image would have nothing to show: we crop it rather than
        # enlarge pixels, which would give the illusion of an optical defect.
        side = min(side, height // n, width // n) or 1

        total = n * side + (n - 1) * marge
        mosaic = np.zeros((total, total, channels), dtype=np.float32)
        for line in range(n):
            for column in range(n):
                # The origins run from 0 to the opposite edge: the corners of the mosaic are
                # therefore the corners of the image, and its center the center.
                sy = int(round(line * (height - side) / (n - 1)))
                sx = int(round(column * (width - side) / (n - 1)))
                dy, dx = line * (side + marge), column * (side + marge)
                mosaic[dy:dy + side, dx:dx + side, :] = data[sy:sy + side, sx:sx + side, :]
        return mosaic


@register
class NoiseEvaluation(Process):
    """Estimates the noise of each channel — the quantity a global MAD does not measure.

    On an image carrying stars, a nebula and a gradient, a robust standard deviation mostly
    measures the **structure**. The question is "what is the spread of the pixels that contain
    *only* noise", and the two must first be separated — which is what the multiresolution
    support does (:mod:`retina.noise_estimation`).

    The difference is not marginal. On a synthetic field with eight thousand stars, injected
    noise 0.0030: the global MAD returns 0.0223, a k-sigma clipping 0.0066, and the
    multiresolution support 0.0029.

    The ``cfa`` mode estimates on the four Bayer sub-planes separately: on an undebayered image,
    a filter mixing two neighboring pixels would measure the difference between two colors, that
    is, the mosaic and not the noise.

    Read-only; result in ``.result``.
    """

    process_id = "NoiseEvaluation"
    category = "ImageInspection"
    supports_realtime = False
    parameters = [
        Parameter("method", "enum", "mrs", choices=("mrs", "ksigma"), label=N_("Method")),
        Parameter("k_sigma", "real", 3.0, 1.0, 10.0, label=N_("Clipping (k·σ)")),
        Parameter("scales", "int", 4, 1, 8, label=N_("Wavelet scales")),
        Parameter("cfa", "bool", False, label=N_("Undebayered CFA image")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    def measure(self, image) -> dict:
        from ..noise_estimation import estimate_noise, split_cfa

        data = image.data if hasattr(image, "data") else np.asarray(image)
        if self.cfa:
            plans = [(f"cfa{i}", p) for i, p in enumerate(split_cfa(data[:, :, 0]))]
        else:
            plans = [(str(c), data[:, :, c]) for c in range(data.shape[2])]

        measures = []
        for name, plan in plans:
            self._checkpoint()
            estimation = estimate_noise(plan, method=self.method, k=float(self.k_sigma),
                                        scales=int(self.scales))
            estimation["channel"] = name
            # The signal-to-noise ratio of the background: this is what we compare from one
            # exposure to the next, a bare spread saying nothing without the level it applies to.
            background = float(np.median(plan))
            estimation["background"] = background
            estimation["snr"] = background / estimation["sigma"] if estimation["sigma"] > 0 else 0.0
            measures.append(estimation)

        self.result = {
            "channels": measures,
            "sigma": float(np.median([m["sigma"] for m in measures])),
            "method": measures[0]["method"] if measures else self.method,
            "cfa": bool(self.cfa),
        }
        return self.result

    def execute_on(self, view) -> bool:  # read-only
        self.measure(view.image)
        return True

    def execute_on_image(self, image):
        self.measure(image)
        return image
