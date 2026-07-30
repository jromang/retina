"""Aperture photometry — measuring the flux of sources, and being able to take it away.

`SourceExtraction` already knows how to *find* sources; what was missing was **measuring**
them properly: a circular aperture, a local background taken from an annulus, an uncertainty,
and an instrumental magnitude. This is the basic gesture of all photometry, and the one light
curves and flux calibration depend on.

# The background annulus, which is not a detail

Subtracting a **global** background from a source assumes the sky is flat. It never is:
light-pollution gradient, halo of a bright star, nebulosity. The annulus measures the sky
*where the source is*, and its median rejects the neighbors that wander into it. Without it,
the photometry of a star at the edge of a nebula is off by a factor, not by a percent.

# Export is a domain gesture

A table you cannot get out is only good to look at. ``output_path`` writes the CSV from the
domain, hence from the console, hence from a script — and the interface button will never do
more than fill in that parameter. That is the parity rule: if export existed only in a panel,
it would be a GUI-only capability, which the project forbids itself.
"""

from __future__ import annotations

import csv
import os

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register
from .stars import detect_sources

#: CSV columns, in order. This is also the contract of ``.result['sources']``.
COLUMNS = ("id", "x", "y", "ra", "dec", "flux", "flux_error", "snr", "magnitude",
           "background", "aperture_area")

#: tag of the overlays laid down by :class:`AperturePhotometry`
PHOTOMETRY_TAG = "aperture-photometry"


def measure_apertures(plan: np.ndarray, xs, ys, radius: float,
                      annulus_inner: float, annulus_outer: float) -> dict:
    """Aperture photometry at **given** positions — the core, without the detection.

    Separated from :class:`AperturePhotometry` because the light curve measures at the same
    places from one frame to the next, without ever re-detecting: two implementations of the
    same computation would have diverged on the very quantity used to compare frames.

    Returns ``{flux, flux_error, background, area, snr, inside}`` — arrays aligned on
    ``xs``/``ys``, with ``inside`` telling which sources have an annulus **entirely within the
    frame**. The others carry a flux measured against a partial background: wrong without
    saying so, hence to be discarded by the caller.
    """
    from photutils.aperture import (
        ApertureStats,
        CircularAnnulus,
        CircularAperture,
        aperture_photometry,
    )

    if annulus_outer <= annulus_inner:
        raise ValueError(
            _t("AperturePhotometry: the background annulus must be a ring — "
               "annulus_outer ({outer}) must exceed annulus_inner ({inner}).").format(
                outer=annulus_outer, inner=annulus_inner))
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    height, width = plan.shape
    inside = ((xs >= annulus_outer) & (xs < width - annulus_outer)
              & (ys >= annulus_outer) & (ys < height - annulus_outer))
    empty = np.zeros(len(xs), dtype=float)
    if not inside.any():
        return {"flux": empty, "flux_error": empty, "background": empty, "area": empty,
                "snr": empty, "inside": inside}

    positions = np.column_stack([xs[inside], ys[inside]])
    apertures = CircularAperture(positions, r=radius)
    annuli = CircularAnnulus(positions, r_in=annulus_inner, r_out=annulus_outer)
    background_stats = ApertureStats(plan, annuli)
    background = np.asarray(background_stats.median, dtype=float)
    noise = np.asarray(background_stats.std, dtype=float)
    area = np.asarray(apertures.area_overlap(plan), dtype=float)
    raw_data = np.asarray(aperture_photometry(plan, apertures)["aperture_sum"], dtype=float)
    flux = raw_data - background * area
    # Background noise integrated over the aperture, plus the uncertainty on the background
    # itself, estimated from the number of pixels in the annulus.
    n_annulus = np.maximum(np.asarray(background_stats.sum_aper_area.value, dtype=float), 1.0)
    error = noise * np.sqrt(area + area * area / n_annulus)

    output = {key: empty.copy() for key in ("flux", "flux_error", "background", "area", "snr")}
    output["flux"][inside] = flux
    output["flux_error"][inside] = error
    output["background"][inside] = background
    output["area"][inside] = area
    with np.errstate(divide="ignore", invalid="ignore"):
        output["snr"][inside] = np.where(error > 0, flux / error, 0.0)
    output["inside"] = inside
    return output


@register
class AperturePhotometry(Process):
    """Flux, uncertainty and instrumental magnitude of the detected sources.

    The background is taken from an **annulus** around each source, not globally: that is what
    makes the measurement valid on a sky that is not flat, which is to say on every sky.

    The uncertainty assumes **Gaussian** noise whose dispersion is measured on the annulus, not
    photon noise — our images are normalized, and the gain that would allow counting electrons
    is not known to the process. It is therefore a *relative* uncertainty, good for comparing
    sources with one another, not for publishing an absolute magnitude.

    Read-only; result in ``.result``, and in a CSV if ``output_path`` is filled in.
    """

    process_id = "AperturePhotometry"
    category = "ImageInspection"
    supports_realtime = False
    parameters = [
        Parameter("fwhm", "real", 3.0, 1.0, 20.0, label=N_("Detection FWHM")),
        Parameter("threshold_sigma", "real", 5.0, 1.0, 50.0, label=N_("Threshold (σ)")),
        Parameter("max_sources", "int", 500, 1, 20000, label=N_("Max sources")),
        Parameter("aperture_radius", "real", 5.0, 0.5, 200.0,
                  label=N_("Aperture radius (px)")),
        Parameter("annulus_inner", "real", 8.0, 0.5, 400.0,
                  label=N_("Background annulus, inner (px)")),
        Parameter("annulus_outer", "real", 12.0, 0.5, 400.0,
                  label=N_("Background annulus, outer (px)")),
        Parameter("channel", "int", -1, -1, 16, label=N_("Channel (-1 = luminance)")),
        Parameter("zero_point", "real", 0.0, -50.0, 50.0,
                  label=N_("Magnitude zero point")),
        Parameter("output_path", "path", "", label=N_("Export to CSV")),
        Parameter("show_apertures", "bool", False, label=N_("Draw apertures")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    def _plan(self, data: np.ndarray) -> np.ndarray:
        channel = int(self.channel)
        if 0 <= channel < data.shape[2]:
            return data[:, :, channel].astype(np.float64)
        return (data.mean(axis=2) if data.shape[2] > 1 else data[:, :, 0]).astype(np.float64)

    def measure(self, image, window=None) -> dict:
        data = image.data if hasattr(image, "data") else np.asarray(image)
        plan = self._plan(data)
        radius = float(self.aperture_radius)
        inner, outer = float(self.annulus_inner), float(self.annulus_outer)

        sources = detect_sources(plan, float(self.fwhm), float(self.threshold_sigma))
        if sources is None or not len(sources):
            self.result = {"n_sources": 0, "sources": [], "columns": list(COLUMNS)}
            return self.result
        sources.sort("flux")
        sources.reverse()
        xcol = "xcentroid" if "xcentroid" in sources.colnames else "x_centroid"
        ycol = "ycentroid" if "ycentroid" in sources.colnames else "y_centroid"
        xs = np.asarray(sources[xcol], dtype=float)[: int(self.max_sources)]
        ys = np.asarray(sources[ycol], dtype=float)[: int(self.max_sources)]

        measure = measure_apertures(plan, xs, ys, radius, inner, outer)
        # A source whose annulus spills out of the frame has no measurable background: keeping
        # it would yield a flux computed against a partial background, hence wrong silently.
        inside = measure["inside"]
        xs, ys = xs[inside], ys[inside]
        if not len(xs):
            self.result = {"n_sources": 0, "sources": [], "columns": list(COLUMNS)}
            return self.result
        flux = measure["flux"][inside]
        error = measure["flux_error"][inside]
        background = measure["background"][inside]
        area = measure["area"][inside]
        snr = measure["snr"][inside]

        ras, decs = self._celestial(window, xs, ys)
        measures = []
        for i in range(len(xs)):
            magnitude = (float(self.zero_point) - 2.5 * np.log10(flux[i])
                         if flux[i] > 0 else None)
            measures.append({
                "id": i, "x": float(xs[i]), "y": float(ys[i]),
                "ra": ras[i], "dec": decs[i],
                "flux": float(flux[i]),
                "flux_error": float(error[i]),
                "snr": float(snr[i]),
                "magnitude": magnitude,
                "background": float(background[i]),
                "aperture_area": float(area[i]),
            })

        self.result = {"n_sources": len(measures), "sources": measures,
                       "columns": list(COLUMNS)}
        if self.output_path:
            self.result["output_path"] = self.export(str(self.output_path))
        return self.result

    @staticmethod
    def _celestial(window, xs, ys):
        """Celestial coordinates if the window is plate-solved, ``None`` otherwise."""
        wcs = getattr(window, "wcs", None) if window is not None else None
        if wcs is None:
            return [None] * len(xs), [None] * len(ys)
        ras, decs = wcs.pixel_to_world_values(xs, ys)
        return [float(v) for v in np.atleast_1d(ras)], [float(v) for v in np.atleast_1d(decs)]

    def export(self, path: str) -> str:
        """Writes the table as CSV. Returns the absolute path actually written."""
        if not self.result:
            raise ValueError(
                _t("AperturePhotometry: nothing to export, run the measurement first."))
        target = os.path.abspath(os.path.expanduser(path))
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as flux:
            writer = csv.DictWriter(flux, fieldnames=list(COLUMNS), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.result["sources"])
        return target

    def overlays(self) -> list[dict]:
        if not self.result or not self.result["sources"]:
            return []
        radius = float(self.aperture_radius)
        return [{
            "kind": "ellipses", "color": (0.3, 1.0, 0.5, 0.9), "width": 1.0,
            "items": [{"x": s["x"], "y": s["y"], "rx": radius, "ry": radius, "theta": 0.0}
                      for s in self.result["sources"]],
        }]

    def execute_on(self, view) -> bool:  # read-only
        self.measure(view.image, window=view.window)
        if self.show_apertures and view.window is not None:
            view.window.viewport.set_overlays(PHOTOMETRY_TAG, self.overlays())
        return True

    def execute_on_image(self, image):
        self.measure(image)
        return image
