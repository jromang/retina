"""SubframeSelector — measures frame quality, scores frames and ranks them.

A read-only **global** process: for each frame it estimates the FWHM, the star
**eccentricity**, their count, the background noise and an SNR, then derives a weight from
them. Used to rank, reject and weight exposures before registration and integration. Creates
no window: the measurements live in ``.measurements`` (and are returned by :meth:`measure`).

# Eccentricity, and why it weighs more than the FWHM

A slightly blurred exposure remains usable; an exposure where tracking drifted produces
elongated stars that will never register cleanly and that will draw streaks in the
integration. That is why the default weighting formula gives it twice the weight of the
FWHM — a setting that comes from common practice, not from a derivation. Eccentricity is
measured from the **second-order moments** of the detected stars: ``e = √(1 − (b/a)²)``,
zero for a disc, tending to 1 for a segment.

# The expressions

``approval`` and ``weighting`` are **Python** expressions evaluated in a sandbox (asteval),
like PixelMath — not a homegrown language. They receive the raw measurements (``fwhm``,
``eccentricity``, ``snr``, ``stars``, ``noise``, ``median``, ``index``) and, for each of
them, four quantities derived from the batch: ``_min``, ``_max``, ``_median`` and ``_sigma``,
plus the historical min-max normalisation ``_n``.

**Prefer ``_sigma`` over ``_n`` to reject.** ``_n`` is a min-max normalisation, hence crushed
by a single outlier: on a batch at 3.0–3.2 px of FWHM containing one botched exposure at
20 px, every good one gets ``fwhm_n ≈ 1`` and they become indistinguishable — the ranking
loses its resolution in exactly the case where it is needed. ``fwhm_sigma`` is the deviation
from the **median**, in units of robust dispersion (MAD × 1.4826): the botched exposure comes
out at 30 σ without squashing the others. This is the usual convention for quantities in σ,
and it reads the same way — positive = above the median.

Writing a criterion then becomes readable and portable from one session to the next:
``fwhm_sigma < 2 and eccentricity < 0.6``.

# Measuring and judging are two distinct steps

:meth:`measure_raw` detects the stars — the dominant cost of a preprocessing run, a handful
of seconds per exposure. :meth:`evaluate` normalises, approves and weights from those
measurements alone: a few microseconds, without touching a pixel. The separation is not
cosmetic. It lets the pipeline **cache the measurements and re-judge on every run**
(cf. :meth:`cache_values`): rejecting six exposures out of a hundred then only recomputes the
integration, whereas conflating the two steps would redo a hundred star detections.

Manual rejection is designated **by path** and not by rank. A frame that calibration could
not produce disappears from the lists along the way; an index would outlive its frame and
reject its neighbour.
"""

from __future__ import annotations

import os

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register

#: default weights of the weighting formula. The pedestal guarantees that a mediocre but
#: valid frame keeps two thirds of the best frame's weight: without it, a homogeneous batch
#: would see its insignificant spread amplified to absurdity.
DEFAULT_WEIGHTING = "65 + 5 * fwhm_n + 10 * eccentricity_n + 20 * snr_n"

#: parameters that bear only on the **judgement**, never on the measurement. Cached
#: measurements therefore stay valid when a criterion or a rejection is adjusted — see
#: :meth:`SubframeSelector.cache_values` and the module header.
#: ``pixel_size``/``focal_length`` are among them: they measure nothing, they **convert** a
#: FWHM into arcseconds. Correcting a wrongly recorded focal length must not redo a star
#: detection over a hundred exposures.
EVALUATION_PARAMETERS = ("approval", "weighting", "min_weight", "manual_rejects",
                         "pixel_size", "focal_length")

#: parameters that describe not *what we measure* but *how we obtain it*. They too are left
#: out of the fingerprint: enabling the persistent cache or not does not change the measurement.
RUNTIME_PARAMETERS = ("use_cache",)

#: normalised quantities offered to the expressions, and how they read
_NORMALISED = {
    "fwhm": False,          # smaller = better
    "eccentricity": False,  # smaller = better
    "noise": False,         # smaller = better
    "snr": True,            # larger = better
    "stars": True,          # larger = better
    "median": True,
    # from the PSF fit; absent from measurements made in "moments" mode, and from files
    # written by an earlier version — `_derive` skips whatever is missing.
    "psf_count": True,              # more successful fits = better founded measurement
    "fwhm_mean_dev": False,         # PSF dispersion across the field: tilt, coma
    "eccentricity_mean_dev": False,
    "psf_flux": True,
    # signal metrics of exposure quality — see `processes/psf.py`
    "psf_signal_weight": True,
    "psf_snr": True,
}

#: suffixes derived from the batch, offered to every measurement. ``_sigma`` is the one to
#: use in order to reject — see the module header.
DERIVED_SUFFIXES = ("_n", "_min", "_max", "_median", "_sigma")

#: factor that makes the MAD a consistent estimator of the Gaussian standard deviation
_MAD_TO_SIGMA = 1.4826


def sample_variables() -> dict:
    """A complete set of plausible variables, to exercise an expression on nothing.

    Used to validate what the user types **before** storing it in a plan: a typo must not
    wait three hours of computation to show up, nor stay stuck in a plan that can no longer
    be read back.
    """
    variables: dict = {"index": 0, "count": 1, "frame": "", "score": 0.0,
                       "approved": True, "weight": 0.0}
    for key in _NORMALISED:
        variables[key] = 1.0
        for suffix in DERIVED_SUFFIXES:
            variables[f"{key}{suffix}"] = 0.5
    return variables


def validate_expression(expression: str) -> str:
    """Error message for an expression, or the empty string if it is acceptable.

    The trial bears on **one** set of values: it catches unknown names and syntax errors —
    the overwhelming majority of real errors — but not a division by a quantity that only
    vanishes on certain data. The check therefore stays useful without claiming to be a
    proof.
    """
    if not expression.strip():
        return ""
    try:
        SubframeSelector._evaluate(expression, sample_variables(), 0.0)
    except ValueError as exc:
        return str(exc).replace("SubframeSelector : expression invalide — ", "")
    except Exception as exc:  # asteval may raise something else on an exotic case
        return f"{type(exc).__name__}: {exc}"
    return ""


def _robust_stats(values: list[float]) -> tuple[float, float]:
    """Median and robust dispersion (MAD × 1.4826) of a batch.

    The MAD rather than the standard deviation: it is precisely the botched exposure we are
    trying to spot that would blow up a standard deviation, and thereby bring everyone back
    into line. A zero dispersion (perfectly homogeneous batch) is returned as such; the
    caller decides what to do with it.
    """
    if not values:
        return 0.0, 0.0
    array = np.asarray(values, dtype=np.float64)
    median = float(np.median(array))
    return median, float(np.median(np.abs(array - median))) * _MAD_TO_SIGMA


def _eccentricity(sources, lum: np.ndarray) -> float:
    """Median star eccentricity, from second-order moments.

    ``photutils`` exposes ``semimajor_sigma``/``semiminor_sigma`` when asked for a
    segmentation; on a plain DAO detection we recompute the moments on a cutout around each
    source, which avoids forcing a second segmentation pass.
    """
    if sources is None or len(sources) == 0:
        return 0.0
    # photutils 3 renames `xcentroid` to `x_centroid` and deprecates the old name: we accept
    # both rather than breaking at the next update.
    columns = set(sources.colnames)
    cx_name = "x_centroid" if "x_centroid" in columns else "xcentroid"
    cy_name = "y_centroid" if "y_centroid" in columns else "ycentroid"
    if cx_name not in columns or cy_name not in columns:
        return 0.0

    radius = 4
    height, width = lum.shape
    values: list[float] = []
    for x0, y0 in zip(sources[cx_name], sources[cy_name], strict=True):
        xi, yi = int(round(float(x0))), int(round(float(y0)))
        if not (radius <= xi < width - radius and radius <= yi < height - radius):
            continue
        cutout = lum[yi - radius:yi + radius + 1, xi - radius:xi + radius + 1]
        weights = np.clip(cutout - np.median(cutout), 0.0, None)
        total = float(weights.sum())
        if total <= 0.0:
            continue
        ys, xs = np.mgrid[-radius:radius + 1, -radius:radius + 1]
        cx = float((weights * xs).sum() / total)
        cy = float((weights * ys).sum() / total)
        xxs, yys = xs - cx, ys - cy
        mxx = float((weights * xxs**2).sum() / total)
        myy = float((weights * yys**2).sum() / total)
        mxy = float((weights * xxs * yys).sum() / total)
        # eigenvalues of the covariance matrix = axes of the ellipse
        commun = np.sqrt(max((mxx - myy) ** 2 / 4.0 + mxy**2, 0.0))
        large = (mxx + myy) / 2.0 + commun
        small = (mxx + myy) / 2.0 - commun
        if large <= 0.0:
            continue
        values.append(float(np.sqrt(max(1.0 - max(small, 0.0) / large, 0.0))))
    return float(np.median(values)) if values else 0.0


def _normalise(values: list[float], plus_grand_est_mieux: bool) -> list[float]:
    """Min-max over the batch, oriented so that 1 is always the best."""
    if not values:
        return []
    bottom, top = min(values), max(values)
    if top - bottom <= 1e-12:
        return [1.0] * len(values)  # homogeneous batch: nobody is better
    scale = [(v - bottom) / (top - bottom) for v in values]
    return scale if plus_grand_est_mieux else [1.0 - e for e in scale]


@register
class SubframeSelector(Process):
    process_id = "SubframeSelector"
    category = "ImageInspection"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Frames")),
        Parameter("fwhm", "real", 3.0, 1.0, 20.0, label=N_("Detection FWHM")),
        Parameter("threshold_sigma", "real", 5.0, 1.0, 50.0, label=N_("Detection threshold (σ)")),
        Parameter("roundness_limit", "real", 3.0, 1.0, 10.0, label=N_("Roundness tolerance"),
                  tooltip=N_("Beyond DAOStarFinder's default (1.0), so that trailed stars are "
                             "detected and measured instead of being ignored")),
        Parameter("psf_model", "enum", "gaussian",
                  choices=("gaussian", "moffat", "moments"), label=N_("PSF model"),
                  tooltip=N_("gaussian: elliptical Gaussian fitted on each star. moffat: "
                             "profile with broader wings, β fitted — closer to the real "
                             "seeing, a little slower. moments: fast estimate without "
                             "fitting, where the FWHM is only a proxy")),
        Parameter("max_fit_stars", "int", 100, 5, 2000, label=N_("Max fits"),
                  tooltip=N_("Number of stars fitted per frame, brightest first. A hundred is "
                             "enough for a stable median; beyond that you pay without gaining")),
        Parameter("pixel_size", "real", 0.0, 0.0, 100.0, label=N_("Pixel size (µm)"),
                  tooltip=N_("0 = read from the header (XPIXSZ). With the focal length, gives "
                             "the FWHM in arcseconds")),
        Parameter("focal_length", "real", 0.0, 0.0, 100000.0, label=N_("Focal length (mm)"),
                  tooltip=N_("0 = read from the header (FOCALLEN)")),
        Parameter("use_cache", "bool", True, label=N_("Measurement cache"),
                  tooltip=N_("Reuses the measurements already computed for a given file, from "
                             "one session to the next. Adding a night then only measures the "
                             "new frames")),
        Parameter("approval", "str", "", label=N_("Approval expression"),
                  tooltip=N_("Python; empty = everything is approved. E.g.: eccentricity < 0.6")),
        Parameter("weighting", "str", "", label=N_("Weighting expression"),
                  tooltip=N_("Python; empty = the default weighting formula")),
        Parameter("min_weight", "real", 0.05, 0.0, 1.0, label=N_("Minimum weight"),
                  tooltip=N_("Fraction of the best score in the batch below which the frame is "
                             "rejected; 0 to reject nothing")),
        Parameter("manual_rejects", "pathlist", [], label=N_("Manual rejects"),
                  tooltip=N_("Frames excluded from stacking by hand: they are still calibrated "
                             "and registered, but carry no weight in the integration")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.measurements: list[dict] = []

    def cache_values(self) -> dict:
        """Only the **detection** settings decide which measurement file is produced.

        Approval criteria, weighting and manual rejects are re-applied on every run by
        :meth:`evaluate`, at negligible cost: including them in the cache fingerprint would
        restart star detection over a whole group at every box ticked in the frame selector.
        """
        exclus = set(EVALUATION_PARAMETERS) | set(RUNTIME_PARAMETERS)
        return {k: v for k, v in self.values().items() if k not in exclus}

    def detection_values(self) -> dict:
        """The settings that decide the measurement of **one** frame, the list excluded.

        This is the persistent cache's key: without removing ``frames``, adding a night to a
        project would change the key of every already-measured exposure and have them
        re-measured — exactly what this cache exists to avoid.
        """
        return {k: v for k, v in self.cache_values().items() if k != "frames"}

    # --- measuring one frame --------------------------------------------------
    def measure_array(self, data: np.ndarray) -> dict:
        from astropy.stats import mad_std, sigma_clipped_stats
        from photutils.detection import DAOStarFinder

        lum = data.mean(axis=2) if data.shape[2] > 1 else data[:, :, 0]
        _, median, std = sigma_clipped_stats(lum, sigma=3.0)
        noise = float(mad_std(lum)) or 1e-6
        # DAOStarFinder's roundness filter is made to *discard* elongated sources —
        # galaxies, cosmics, artefacts. Keeping it at its default here would be
        # self-contradictory: on an exposure where tracking drifted, it detects no star at
        # all, and the absence of a measurement would read as a perfect frame. So we widen
        # it, so that trailed stars are seen *and* penalised.
        limit = float(self.roundness_limit)
        sources = DAOStarFinder(fwhm=self.fwhm, threshold=self.threshold_sigma * std,
                                roundlo=-limit, roundhi=limit)(lum - median)
        n_stars = 0 if sources is None else len(sources)
        measure = {
            "stars": n_stars,
            "noise": noise,
            "snr": float(median / noise),
            "median": float(median),
        }
        measure.update(self._shape(lum, sources, float(median)))
        measure.update(self._signal(lum, measure))
        return measure

    def _signal(self, lum: np.ndarray, measure: dict) -> dict:
        """PSF Signal Weight and PSF SNR — published formulas, in-house estimators.

        Costs something only if the fit succeeded: without measured stars these quantities
        have no meaning, and the background model would be computed for nothing.
        """
        from .psf import local_background_residual, m_star, n_star, psf_signal_weight, psf_snr

        flux_total = float(measure.get("psf_signal", 0.0) or 0.0)
        flux_moyen = float(measure.get("psf_mean_signal", 0.0) or 0.0)
        if flux_total <= 0.0 or flux_moyen <= 0.0:
            return {}
        residual = local_background_residual(lum)
        background, noise = m_star(residual), n_star(residual)
        return {
            "m_star": background,
            "n_star": noise,
            "psf_signal_weight": psf_signal_weight(flux_total, flux_moyen, background, noise),
            "psf_snr": psf_snr(flux_total, noise),
        }

    def _shape(self, lum: np.ndarray, sources, background: float) -> dict:
        """FWHM, eccentricity and PSF uniformity across the field.

        By fitting when possible, by moments otherwise. The fallback is not a convenience:
        on an exposure without a usable star, the fit returns nothing, and a coarse estimate
        beats a hole in the sorting column.
        """
        from .psf import PSF_FUNCTIONS, fit_psf_stars

        stars: list[dict] = []
        if sources is not None and len(sources) and self.psf_model in PSF_FUNCTIONS:
            columns = set(sources.colnames)
            cx = "x_centroid" if "x_centroid" in columns else "xcentroid"
            cy = "y_centroid" if "y_centroid" in columns else "ycentroid"
            if cx in columns and cy in columns:
                # Brightest first: on a bounded fitting budget, those are the ones whose
                # shape is best constrained.
                order = (np.argsort(np.asarray(sources["flux"], dtype=float))[::-1]
                         if "flux" in columns else np.arange(len(sources)))
                xs = np.asarray(sources[cx], dtype=float)[order]
                ys = np.asarray(sources[cy], dtype=float)[order]
                stars = fit_psf_stars(lum, xs, ys, fwhm_guess=float(self.fwhm),
                                        background=background,
                                        limit=int(self.max_fit_stars),
                                        function=str(self.psf_model))

        if not stars:
            # Proxy: DAO exposes a width through "sharpness". That is not a FWHM, and the
            # name says so — hence the fit in normal mode.
            proxy = float(self.fwhm)
            if sources is not None and len(sources) and "sharpness" in sources.colnames:
                proxy = float(self.fwhm / max(np.median(sources["sharpness"]), 1e-3))
            return {"fwhm": proxy, "eccentricity": _eccentricity(sources, lum),
                    "psf_count": 0, "fwhm_mean_dev": 0.0, "eccentricity_mean_dev": 0.0,
                    "psf_flux": 0.0}

        fwhms = np.array([e["fwhm"] for e in stars], dtype=float)
        eccs = np.array([e["eccentricity"] for e in stars], dtype=float)
        return {
            "fwhm": float(np.median(fwhms)),
            "eccentricity": float(np.median(eccs)),
            "psf_count": len(stars),
            # PSF dispersion **across the field**, not from one exposure to the next: that
            # is what betrays sensor tilt or coma, which a median alone would hide.
            "fwhm_mean_dev": float(np.mean(np.abs(fwhms - np.median(fwhms)))),
            "eccentricity_mean_dev": float(np.mean(np.abs(eccs - np.median(eccs)))),
            "psf_flux": float(np.sum([e["flux"] for e in stars])),
            # Flux **measured** over the elliptical region, and its per-pixel mean: the two
            # sums PSF Signal Weight needs (ΣF and ΣF̄).
            "psf_signal": float(np.sum([e["signal"] for e in stars])),
            "psf_mean_signal": float(np.sum([e["signal"] / e["signal_count"]
                                             for e in stars])),
        }

    # --- expressions ----------------------------------------------------------
    @staticmethod
    def _evaluate(expression: str, variables: dict, default: float) -> float:
        from asteval import Interpreter as ASTEval

        interprete = ASTEval(minimal=True, no_print=True)
        interprete.symtable.update(variables)
        result = interprete(expression)
        if interprete.error:
            messages = "; ".join(e.get_error()[1] for e in interprete.error)
            raise ValueError(
                _t("SubframeSelector: invalid expression — {errors}").format(errors=messages))
        if result is None:
            return default
        return float(result)

    def _scale(self, rows: list[dict]) -> None:
        """Adds ``fwhm_arcsec`` when the scale is known.

        A FWHM in pixels does not compare from one instrument to another, and says nothing
        about the seeing. The computation is done **here** and not at measurement time: it is
        a conversion, so correcting a wrongly recorded focal length must not re-measure
        anything.
        """
        from .psf import pixel_scale

        force = pixel_scale(float(self.pixel_size), float(self.focal_length))
        for line in rows:
            scale = force or float(line.get("pixel_scale", 0.0) or 0.0)
            if scale > 0.0:
                line["fwhm_arcsec"] = float(line["fwhm"]) * scale
            else:
                line.pop("fwhm_arcsec", None)

    @staticmethod
    def _derive(rows: list[dict]) -> None:
        """Adds to each measurement its quantities derived from the batch.

        ``_n`` (min-max, oriented so that "1 = the best") is kept: the default weighting
        formula relies on it, and weighting *is* its proper use — there we precisely want the
        best of the batch to score 1. To **reject**, ``_sigma`` is the one to use: a min-max
        gets crushed by the very botched exposure we are trying to remove.
        """
        for key, highest in _NORMALISED.items():
            # A measurement file written before a quantity existed does not carry it.
            # Deriving it anyway would make it worth zero everywhere — a perfect batch on a
            # criterion that was never measured. We skip it, and the expression that uses it
            # will fail saying so.
            if any(key not in line for line in rows):
                continue
            values = [float(r[key]) for r in rows]
            median, sigma = _robust_stats(values)
            bottom, top = (min(values), max(values)) if values else (0.0, 0.0)
            normalisees = _normalise(values, highest)
            for line, raw, norm in zip(rows, values, normalisees, strict=True):
                line[f"{key}_n"] = norm
                line[f"{key}_min"] = bottom
                line[f"{key}_max"] = top
                line[f"{key}_median"] = median
                # Zero dispersion = perfectly homogeneous batch: nobody deviates from
                # anybody. Zero is the only right answer, and it avoids the division.
                line[f"{key}_sigma"] = (raw - median) / sigma if sigma > 1e-12 else 0.0

    def _apply_expressions(self, rows: list[dict]) -> None:
        """Adds the batch-derived quantities, ``approved``, ``rejected_by`` and ``weight``."""
        self._scale(rows)
        self._derive(rows)

        rejets = {os.path.normpath(str(p)) for p in self.manual_rejects}
        expression = self.weighting or DEFAULT_WEIGHTING
        for index, line in enumerate(rows):
            # a re-evaluation starts from scratch: keeping the previous round's reason would
            # display "rejected by the expression" on a frame that the expression has
            # precisely just re-admitted.
            line.pop("rejected_by", None)
            variables = dict(line, index=index, count=len(rows))
            approuve = True
            if self.approval and not self._evaluate(self.approval, variables, 1.0):
                approuve = False
                line["rejected_by"] = "expression"
            # Manual rejection wins: it is explicit, and it is the reason the user must read
            # even if an automatic criterion had already rejected the frame.
            if rejets and os.path.normpath(str(line.get("frame", ""))) in rejets:
                approuve = False
                line["rejected_by"] = "manual"
            line["approved"] = approuve
            line["score"] = max(self._evaluate(expression, variables, 0.0), 0.0)

        # Floor relative to the best of the batch: an exposure twenty times worse than the
        # best brings nothing to the average and degrades rejection, which will treat it as a
        # permanent outlier. The threshold is relative, hence portable from batch to batch.
        plancher = float(self.min_weight)
        if plancher > 0.0:
            meilleur = max((r["score"] for r in rows if r["approved"]), default=0.0)
            for line in rows:
                if line["approved"] and line["score"] < plancher * meilleur:
                    line["approved"] = False
                    line["rejected_by"] = "min_weight"

        # A refused frame carries no weight, but stays in the report: the user must be able
        # to see *why* it was rejected, not only that it disappeared.
        total = sum(r["score"] for r in rows if r["approved"]) or 1.0
        for line in rows:
            line["weight"] = line["score"] / total if line["approved"] else 0.0

    # --- execution ------------------------------------------------------------
    @staticmethod
    def _scale_from_header(path: str) -> float:
        """Scale in arcsec/pixel read from the header, or 0 if it is not there.

        ``XPIXSZ``/``FOCALLEN`` are the keywords written by NINA, SGP and ASCOM; by
        convention ``XPIXSZ`` already reflects binning. One more header read per exposure
        weighs nothing next to a star detection.
        """
        from ..io.fits import load_fits_header
        from .psf import pixel_scale

        try:
            header = load_fits_header(path)
        except Exception:
            return 0.0
        try:
            return pixel_scale(float(header.get("XPIXSZ", 0) or 0),
                               float(header.get("FOCALLEN", 0) or 0))
        except (TypeError, ValueError):
            return 0.0

    def measure_raw(self) -> list[dict]:
        """The measurements alone, without judgement — the expensive part, the cached one.

        The persistent cache works **per file**, where the run cache works per step: adding
        a night only re-measures the exposures that were added.
        """
        from ..io import load_image_array
        from ..pipeline.measure_cache import MeasureCache

        repo = MeasureCache() if self.use_cache else None
        settings = self.detection_values()
        rows = []
        total = len(self.frames)
        for index, p in enumerate(self.frames):
            self._progress(index / max(total, 1), _t("Measurement {n}/{total}").format(
                n=index + 1, total=total))
            m = repo.get(p, settings) if repo is not None else None
            if m is None:
                m = self.measure_array(load_image_array(p).astype(np.float32))
                m["pixel_scale"] = self._scale_from_header(p)
                if repo is not None:
                    repo.put(p, settings, m)
            m["frame"] = p
            rows.append(m)
        if repo is not None:
            repo.flush()
        self._progress(1.0, _t("Measurements complete"))
        return rows

    def evaluate(self, rows: list[dict]) -> list[dict]:
        """Judges measurements already made: normalisation, approval, weight.

        **Idempotent** — normalised quantities and rejection reasons are recomputed from the
        raw measurements, never accumulated. That is what makes it possible to read a
        measurement file back and re-judge it with other criteria without re-measuring
        anything.

        >>> selecteur.manual_rejects = ["/data/light_007.fits"]
        >>> selecteur.evaluate(mesures)[7]["rejected_by"]
        'manual'
        """
        if rows:
            self._apply_expressions(rows)
        self.measurements = rows
        return rows

    def measure(self) -> list[dict]:
        """Measures then judges — the full chain, as a run performs it."""
        return self.evaluate(self.measure_raw())

    def approved(self) -> list[dict]:
        """The only measurements the integration should consume."""
        return [r for r in self.measurements if r.get("approved", True)]

    def execute_global(self, app) -> bool:
        self.measure()
        return True
