"""Star tools: detection → star mask (photutils DAOStarFinder)."""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def detect_sources(lum: np.ndarray, fwhm: float, threshold_sigma: float):
    """Detects stars on a 2D luminance image (photutils DAOStarFinder)."""
    from astropy.stats import sigma_clipped_stats
    from photutils.detection import DAOStarFinder

    _, median, std = sigma_clipped_stats(lum, sigma=3.0)
    return DAOStarFinder(fwhm=fwhm, threshold=threshold_sigma * std)(lum - median)


def star_mask(shape: tuple[int, int], sources, radius: float) -> np.ndarray:
    """Boolean mask: disks of radius ``radius`` around the detected stars."""
    h, w = shape
    mask = np.zeros((h, w), dtype=bool)
    if sources is None:
        return mask
    xcol = "xcentroid" if "xcentroid" in sources.colnames else "x_centroid"
    ycol = "ycentroid" if "ycentroid" in sources.colnames else "y_centroid"
    ri = int(np.ceil(radius))
    for s in sources:
        cx, cy = float(s[xcol]), float(s[ycol])
        x0, x1 = max(0, int(cx) - ri), min(w, int(cx) + ri + 1)
        y0, y1 = max(0, int(cy) - ri), min(h, int(cy) + ri + 1)
        ys, xs = np.ogrid[y0:y1, x0:x1]
        disk = (xs - cx) ** 2 + (ys - cy) ** 2 <= radius * radius
        mask[y0:y1, x0:x1][disk] = True
    return mask


@register
class StarMask(Process):
    """Detects the stars and produces a mask (1 channel) in a NEW window.

    The catalog from the last run is in ``.stars``.
    """

    process_id = "StarMask"
    category = "MaskGeneration"
    creates_window = True  # generates a mask without destroying the source image
    is_maskable = False
    parameters = [
        Parameter("fwhm", "real", 3.0, 1.0, 20.0, label=N_("FWHM")),
        Parameter("threshold_sigma", "real", 5.0, 1.0, 50.0, label=N_("Threshold (σ)")),
        Parameter("radius", "real", 4.0, 1.0, 50.0, label=N_("Mask radius")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stars = None  # catalog from the last run

    def _apply(self, data: np.ndarray) -> np.ndarray:
        lum = data.mean(axis=2)
        self.stars = detect_sources(lum, self.fwhm, self.threshold_sigma)
        mask = star_mask(lum.shape, self.stars, self.radius).astype(np.float32)
        return mask[:, :, None]


@register
class StarReduction(Process):
    """Reduces the apparent size of stars without touching the rest of the image.

    Three methods, in the spirit of those Bill Blanshan popularized in PixelMath. The formulas
    below are our own; what is borrowed is the **principle** of each.

    ``transfer`` and ``halo`` require a **starless** image (parameter ``starless``, a view
    identifier — see :class:`~retina.processes.starremoval.StarRemoval`). That is what makes
    them precise: we know exactly what is a star and what is not.

    - ``transfer`` — the star layer is extracted by the **screen model**
      ``I = 1 − (1−L)(1−S)``, attenuated, then recomposed. This is the gentlest method: it
      distorts nothing, it darkens.
    - ``halo`` — the same extraction, but the star layer is **eroded** before recomposition.
      Stars shrink instead of fading, which suits large halos.
    - ``morphological`` — needs no starless image at all: a **minimum** filter over the image,
      blended with the original according to ``strength``. Less precise (it bites into fine
      structures that are not stars), but available right away.

    Why the screen model rather than a subtraction: two overlapping light sources do not add
    linearly once the image is normalized, and a subtraction leaves black holes at the cores of
    bright stars — right where the image saturates.
    """

    process_id = "StarReduction"
    category = "MaskGeneration"
    parameters = [
        Parameter("method", "enum", "transfer",
                  choices=("transfer", "halo", "morphological"), label=N_("Method")),
        Parameter("starless", "str", "", label=N_("Starless view")),
        Parameter("strength", "real", 0.5, 0.0, 1.0, label=N_("Strength")),
        Parameter("iterations", "int", 1, 1, 10, label=N_("Iterations")),
    ]

    def _starless(self, data: np.ndarray) -> np.ndarray:
        from ..process import context

        if not self.starless:
            raise ValueError(
                _t("StarReduction(method={method!r}): parameter 'starless' required "
                   "(the identifier of a starless view). Otherwise, use "
                   "method='morphological'.").format(method=self.method))
        arr = context.resolve_image_full(self.starless)
        if arr is None:
            raise ValueError(
                _t("StarReduction: starless view not found ({view!r})").format(view=self.starless))
        if arr.shape[:2] != data.shape[:2]:
            raise ValueError(
                _t("StarReduction: the starless view is {view_shape}, the image is {shape} — "
                   "they must share the same geometry.").format(
                    view_shape=arr.shape[:2], shape=data.shape[:2]))
        if arr.shape[2] != data.shape[2]:
            arr = np.repeat(arr.mean(axis=2)[:, :, None], data.shape[2], axis=2)
        return np.clip(arr, 0.0, 1.0)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        image = np.clip(data, 0.0, 1.0).astype(np.float64)
        force = float(np.clip(self.strength, 0.0, 1.0))
        if force <= 0.0:
            return data.copy()

        if self.method == "morphological":
            from scipy.ndimage import minimum_filter

            reduced = image
            for _ in range(int(self.iterations)):
                self._checkpoint()
                reduced = np.stack(
                    [minimum_filter(reduced[:, :, c], size=3) for c in range(image.shape[2])],
                    axis=2)
            return ((1.0 - force) * image + force * reduced).astype(np.float32)

        sans = self._starless(image)
        # Star layer by the screen model, clamped: beyond 1 the ratio no longer makes sense,
        # and a starless image locally *brighter* than the original does happen.
        stars = np.clip(1.0 - (1.0 - image) / np.maximum(1.0 - sans, 1e-6), 0.0, 1.0)

        if self.method == "halo":
            from scipy.ndimage import minimum_filter

            for _ in range(int(self.iterations)):
                self._checkpoint()
                stars = np.stack(
                    [minimum_filter(stars[:, :, c], size=3) for c in range(image.shape[2])],
                    axis=2)
        else:                                   # transfer: attenuate without distorting
            stars = stars * (1.0 - force)

        recompose = 1.0 - (1.0 - sans) * (1.0 - stars)
        if self.method == "halo":
            recompose = (1.0 - force) * image + force * recompose
        return np.clip(recompose, 0.0, 1.0).astype(np.float32)
