"""Source detection — a SExtractor-style catalog (read-only).

``SourceExtraction`` segments the image (photutils), deblends the merged sources and measures
flux/centroid/ellipticity — the basis of a star mask in a dense field or of a quality check.
``SEPBackground``/``SEPSourceExtraction`` offer a **very fast** route through the ``sep``
library (native Source-Extractor). Lazy imports.
"""

from __future__ import annotations

import contextlib

import numpy as np

from ..i18n import N_
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class SourceExtraction(Process):
    """Source catalog (segmentation + deblending, photutils) — read-only.

    The result of the last run is in ``.result``: number of sources and table
    (x, y, flux, area, ellipticity). Does not modify the image (like ``Statistics``).
    """

    process_id = "SourceExtraction"
    category = "ImageInspection"
    parameters = [
        Parameter("threshold_sigma", "real", 3.0, 0.5, 50.0,
                  label=N_("Threshold (σ above background)")),
        Parameter("npixels", "int", 5, 1, 1000, label=N_("Min connected pixels")),
        Parameter("deblend", "bool", True, label=N_("Deblend merged sources")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    def measure(self, image) -> dict:
        from astropy.stats import sigma_clipped_stats
        from photutils.segmentation import SourceCatalog, deblend_sources, detect_sources

        d = image.data if hasattr(image, "data") else np.asarray(image)
        lum = d.mean(axis=2) if d.shape[2] > 1 else d[:, :, 0]
        _, median, std = sigma_clipped_stats(lum, sigma=3.0)
        threshold = median + self.threshold_sigma * std
        npix = int(self.npixels)

        def _npix_kw() -> dict:  # photutils ≥3 renames npixels → n_pixels
            import inspect

            params = inspect.signature(detect_sources).parameters
            return {"n_pixels": npix} if "n_pixels" in params else {"npixels": npix}

        kw = _npix_kw()
        segm = detect_sources(lum, threshold, **kw)
        if segm is None:
            self.result = {"n_sources": 0, "sources": []}
            return self.result
        if self.deblend:
            with contextlib.suppress(Exception):
                segm = deblend_sources(lum, segm, **kw)
        cat = SourceCatalog(lum - median, segm)
        # the catalog properties are aligned arrays (one entry per source).
        # photutils ≥3 renames xcentroid→x_centroid: take whichever name is available.
        xc = np.atleast_1d(getattr(cat, "x_centroid", None)
                           if hasattr(cat, "x_centroid") else cat.xcentroid)
        yc = np.atleast_1d(getattr(cat, "y_centroid", None)
                           if hasattr(cat, "y_centroid") else cat.ycentroid)
        flux = np.atleast_1d(cat.segment_flux)
        area = np.atleast_1d(cat.area)
        ecc = np.atleast_1d(cat.eccentricity)
        sources = [
            {
                "x": float(xc[i]),
                "y": float(yc[i]),
                "flux": float(flux[i]),
                "area": float(getattr(area[i], "value", area[i])),
                "eccentricity": float(ecc[i]),
            }
            for i in range(len(xc))
        ]
        self.result = {"n_sources": len(sources), "sources": sources}
        return self.result

    def execute_on(self, view) -> bool:  # read-only: no history entry
        self.measure(view.image)
        return True

    def execute_on_image(self, image):
        self.measure(image)
        return image


@register
class SEPBackground(Process):
    """Background estimation + subtraction via ``sep`` (native Source-Extractor, very fast).

    A high-performance alternative to ``BackgroundExtraction`` (photutils) on wide fields.
    ``subtract=False`` outputs the background model instead of the subtracted image.
    """

    process_id = "SEPBackground"
    category = "BackgroundModelization"
    parameters = [
        Parameter("box_size", "int", 64, 4, 1024, label=N_("Box size")),
        Parameter("filter_size", "int", 3, 1, 15, label=N_("Median filter size")),
        Parameter("subtract", "bool", True, label=N_("Subtract (otherwise: output the model)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import sep

        bw = int(self.box_size)
        fw = int(self.filter_size)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            # sep requires a C-contiguous array in native byte order
            ch = np.ascontiguousarray(data[:, :, c], dtype=np.float32)
            bkg = sep.Background(ch, bw=bw, bh=bw, fw=fw, fh=fw)
            model = bkg.back()
            out[:, :, c] = (ch - model) if self.subtract else model
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class SEPSourceExtraction(Process):
    """Source detection via ``sep.extract`` (read-only, very fast).

    First subtracts the ``sep`` background, then extracts the sources above
    ``threshold_sigma`` times the global noise. Result in ``.result`` (x, y, flux, area).
    """

    process_id = "SEPSourceExtraction"
    category = "ImageInspection"
    parameters = [
        Parameter("threshold_sigma", "real", 3.0, 0.5, 50.0, label=N_("Threshold (σ)")),
        Parameter("min_area", "int", 5, 1, 1000, label=N_("Min area (pixels)")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    def measure(self, image) -> dict:
        import sep

        d = image.data if hasattr(image, "data") else np.asarray(image)
        lum = np.ascontiguousarray(
            d.mean(axis=2) if d.shape[2] > 1 else d[:, :, 0], dtype=np.float32
        )
        bkg = sep.Background(lum)
        sub = lum - bkg.back()
        objs = sep.extract(sub, self.threshold_sigma, err=bkg.globalrms,
                           minarea=int(self.min_area))
        sources = [
            {"x": float(o["x"]), "y": float(o["y"]),
             "flux": float(o["flux"]), "area": int(o["npix"])}
            for o in objs
        ]
        self.result = {"n_sources": len(sources), "sources": sources}
        return self.result

    def execute_on(self, view) -> bool:
        self.measure(view.image)
        return True

    def execute_on_image(self, image):
        self.measure(image)
        return image
