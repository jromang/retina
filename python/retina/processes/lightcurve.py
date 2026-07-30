"""Light curves — measuring a variable star frame after frame, and being able to submit it.

There was nothing here: `AperturePhotometry` measures *one* image, and nothing knew how to
follow a target from one frame to the next, nor to date what it measured.

# The pattern is that of SubframeSelector, and that is no accident

Measuring is expensive, judging is free. `measure_raw` does the photometry of each file and
caches it **per file**; `evaluate` derives from it the magnitudes, the differential, the
exports — in a few microseconds. Changing differential mode, re-exporting to AAVSO, adding a
frame: none of that re-measures the series.

# Differential photometry, and why it is the default

A raw instrumental magnitude follows sky transparency, air mass and dew on the corrector; it
says next to nothing about the star. Referred to **comparison** stars in the same field,
measured in the same frame and through the same atmosphere, all of that cancels out. That is
why the default mode is the ensemble: several comparisons weigh less than a single one if one
of them turns out to be variable, which happens.

# Following the target without re-solving every frame

Three paths, from the safest to the most general, tried in that order: the header WCS when the
frame carries one (the pipeline's registered outputs propagate it), otherwise a star match
against the first frame (`astroalign`, whose detections are cached by the existing
`StarCache`). In both cases the predicted position is **recentered** on the local barycenter:
it is that recentering, and not the accuracy of the WCS, that makes the measurement robust — an
aperture off by two pixels loses flux, and loses *a varying amount of it from one frame to the
next*, which fabricates spurious variability.

# What we did not do

No BJD: the barycentric correction requires the observer's position and the target's, and the
AAVSO format accepts JD (`#DATE=JD`) — which is where comparable tools stop as well. No
periodogram and no transit fitting: the aim is a dependable photometric series, not a
time-series analysis package.
"""

from __future__ import annotations

import csv
import os

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register
from .photometry import measure_apertures

#: Columns of the CSV and of ``.result['points']``.
COLUMNS = ("frame", "jd", "filter", "airmass", "mag", "mag_err", "check_mag",
           "target_flux", "target_flux_error", "comparison_flux")

#: Parameters that only change the **judgement**: excluding them from the cache fingerprint
#: is what makes a replay instantaneous. Same mechanism as ``SubframeSelector``.
EVALUATION_PARAMETERS = ("mode", "obscode", "filter", "chart", "notes",
                         "output_csv", "output_aavso")

#: Runtime parameters, which describe no result.
RUNTIME_PARAMETERS = ("use_cache",)

#: The AAVSO format's value for an unknown field. It is not an empty string: the format
#: requires it explicitly, and an empty column would be read there as a column shift.
AAVSO_ABSENT = "na"


def parse_stars(text: str) -> list[dict]:
    """Reads a list of stars ``"ra,dec[,mag]"`` or ``"x:y"``, separated by ``;``.

    Two syntaxes because there are two situations. On a solved field, we designate stars by
    celestial coordinates — that is what an AAVSO chart gives, and it survives a field
    rotation. On an unsolved series, we designate them by pixel on the **first** frame, and
    the matching propagates them. The ``x:y`` notation makes the two impossible to confuse.

    The magnitude, optional, is the catalogue one: providing it turns the output from
    differential (``MTYPE=DIF``) into standardized (``MTYPE=STD``).
    """
    stars = []
    for chunk in str(text or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            x, _, y = chunk.partition(":")
            stars.append({"x": float(x), "y": float(y)})
            continue
        fields = [c.strip() for c in chunk.split(",")]
        if len(fields) < 2:
            raise ValueError(
                _t("Cannot read star {text!r} — expected 'ra,dec[,mag]' or 'x:y'.").format(
                    text=chunk))
        star = {"ra": float(fields[0]), "dec": float(fields[1])}
        if len(fields) > 2 and fields[2]:
            star["mag"] = float(fields[2])
        stars.append(star)
    return stars


def format_stars(stars) -> str:
    """Inverse of :func:`parse_stars` — what makes ``set_stars`` scriptable."""
    chunks = []
    for star in stars:
        if "x" in star:
            chunks.append(f"{float(star['x'])}:{float(star['y'])}")
        elif star.get("mag") is not None:
            chunks.append(f"{float(star['ra'])},{float(star['dec'])},"
                            f"{float(star['mag'])}")
        else:
            chunks.append(f"{float(star['ra'])},{float(star['dec'])}")
    return ";".join(chunks)


@register
class LightCurve(Process):
    """Differential photometry of a target over a series of frames, exportable to AAVSO.

    **Global** process: it reads a list of files and touches no view. The result is in
    ``.result`` (and in the files requested by ``output_csv`` / ``output_aavso``, which are
    domain parameters, not buttons).

    >>> curve = LightCurve(frames=sorted(glob("/data/V1234/*.fits")))
    >>> curve.set_stars(target=(210.51, 33.02), comparisons=[(210.48, 33.05, 11.42)])
    >>> curve.measure()[0]["mag"]
    """

    process_id = "LightCurve"
    category = "ImageInspection"
    is_global = True
    supports_realtime = False
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Frames")),
        Parameter("target", "str", "", label=N_("Target star"),
                  tooltip=N_("'ra,dec' in degrees, or 'x:y' in pixels of the first frame")),
        Parameter("comparisons", "str", "", label=N_("Comparison stars"),
                  tooltip=N_("Same syntax, separated by ';'. A third value is the catalogue "
                             "magnitude, which turns the output into standard magnitudes")),
        Parameter("check", "str", "", label=N_("Check star"),
                  tooltip=N_("Measured like the target but never used to correct it: its "
                             "flatness is what proves the run is trustworthy")),
        Parameter("mode", "enum", "ensemble",
                  choices=("ensemble", "single", "instrumental"),
                  label=N_("Photometry mode")),
        Parameter("aperture_radius", "real", 5.0, 0.5, 200.0,
                  label=N_("Aperture radius (px)")),
        Parameter("annulus_inner", "real", 8.0, 0.5, 400.0,
                  label=N_("Background annulus, inner (px)")),
        Parameter("annulus_outer", "real", 12.0, 0.5, 400.0,
                  label=N_("Background annulus, outer (px)")),
        Parameter("channel", "int", -1, -1, 16, label=N_("Channel (-1 = luminance)")),
        Parameter("matching", "enum", "auto", choices=("auto", "wcs", "align"),
                  label=N_("Frame matching")),
        Parameter("recenter", "bool", True, label=N_("Recentre on each frame"),
                  tooltip=N_("An aperture off by two pixels loses a varying amount of flux "
                             "from frame to frame, which fabricates variability")),
        Parameter("use_cache", "bool", True, label=N_("Reuse cached measurements")),
        Parameter("obscode", "str", "", label=N_("AAVSO observer code")),
        Parameter("filter", "str", "", label=N_("Filter (empty = FITS FILTER keyword)")),
        Parameter("chart", "str", "", label=N_("AAVSO chart id")),
        Parameter("notes", "str", "", label=N_("Notes")),
        Parameter("output_csv", "path", "", label=N_("Export to CSV")),
        Parameter("output_aavso", "path", "", label=N_("Export to AAVSO format")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.measurements: list[dict] = []
        self.result: dict | None = None
        self._reference = None  # (path, plane, wcs) of the first frame

    # --- star designation -------------------------------------------------------
    def set_stars(self, target=None, comparisons=None, check=None) -> LightCurve:
        """Console convenience: sets the stars from tuples rather than from strings.

        The parameters stay strings — that is what makes them serializable, replayable and
        displayable by the auto-generated form without inventing a field type.

        >>> curve.set_stars(target=(210.51, 33.02),
        ...                 comparisons=[(210.48, 33.05, 11.42), (210.55, 32.99)])
        """
        def encode(value):
            if value is None:
                return None
            if isinstance(value, (list, tuple)) and value and isinstance(
                    value[0], (list, tuple)):
                stars = value
            else:
                stars = [value]
            return format_stars([_tuple_to_star(e) for e in stars])

        if target is not None:
            self.target = encode(target)
        if comparisons is not None:
            self.comparisons = encode(comparisons)
        if check is not None:
            self.check = encode(check)
        return self

    def stars(self) -> list[dict]:
        """Every star to be measured, each carrying its role."""
        stars = []
        for star in parse_stars(self.target):
            stars.append({**star, "role": "target"})
        for star in parse_stars(self.comparisons):
            stars.append({**star, "role": "comparison"})
        for star in parse_stars(self.check):
            stars.append({**star, "role": "check"})
        if not any(e["role"] == "target" for e in stars):
            raise ValueError(_t("LightCurve: no target star given."))
        return stars

    # --- cache keys --------------------------------------------------------------
    def cache_values(self) -> dict:
        exclus = set(EVALUATION_PARAMETERS) | set(RUNTIME_PARAMETERS)
        return {k: v for k, v in self.values().items() if k not in exclus}

    def detection_values(self) -> dict:
        """What decides the measurement of **one** frame — the frame list excluded.

        Without that removal, adding a frame to the series would change the key of every other
        one and make them all re-measure: exactly what the cache exists to avoid.
        """
        return {k: v for k, v in self.cache_values().items() if k != "frames"}

    # --- measuring one frame ------------------------------------------------------
    def _plan(self, data: np.ndarray) -> np.ndarray:
        channel = int(self.channel)
        if 0 <= channel < data.shape[2]:
            return data[:, :, channel].astype(np.float64)
        return (data.mean(axis=2) if data.shape[2] > 1 else data[:, :, 0]).astype(np.float64)

    def _positions(self, path: str, plan: np.ndarray, keywords: dict,
                   stars: list[dict]) -> np.ndarray:
        """Pixel positions of the stars in **this** frame."""
        from ..io.fits import celestial_wcs

        mode = str(self.matching)
        wcs = celestial_wcs(keywords) if mode in ("auto", "wcs") else None
        if wcs is not None and all("ra" in e for e in stars):
            xs, ys = wcs.world_to_pixel_values(
                [float(e["ra"]) for e in stars], [float(e["dec"]) for e in stars])
            return np.column_stack([np.atleast_1d(xs), np.atleast_1d(ys)])
        if mode == "wcs":
            raise ValueError(
                _t("LightCurve: frame {frame} carries no WCS (matching='wcs').").format(
                    frame=os.path.basename(path)))
        return self._positions_par_recalage(path, plan, stars)

    def _positions_par_recalage(self, path: str, plan: np.ndarray,
                                stars: list[dict]) -> np.ndarray:
        """Positions carried over from the first frame by star matching."""
        base = self._positions_de_reference(stars)
        if self._reference is None or self._reference[0] == path:
            return base
        import astroalign

        try:
            transformation, _ = astroalign.find_transform(self._reference[1], plan)
        except Exception as exc:
            raise ValueError(
                _t("LightCurve: cannot match frame {frame} to the first one — "
                   "give a WCS or align the series first.").format(
                       frame=os.path.basename(path))) from exc
        return np.asarray(transformation(base), dtype=float)

    def _positions_de_reference(self, stars: list[dict]) -> np.ndarray:
        """Pixel positions on the first frame — the starting point of the transport."""
        if all("x" in e for e in stars):
            return np.array([[float(e["x"]), float(e["y"])] for e in stars], dtype=float)
        if self._reference is None or self._reference[2] is None:
            raise ValueError(
                _t("LightCurve: celestial coordinates need a WCS on the first frame, "
                   "or give pixel positions as 'x:y'."))
        wcs = self._reference[2]
        xs, ys = wcs.world_to_pixel_values(
            [float(e["ra"]) for e in stars], [float(e["dec"]) for e in stars])
        return np.column_stack([np.atleast_1d(xs), np.atleast_1d(ys)])

    def _recentrer(self, plan: np.ndarray, positions: np.ndarray) -> np.ndarray:
        """Snaps each aperture onto the local barycenter.

        This is the piece that makes the whole thing robust: neither the WCS nor the matching
        is pixel-perfect, and an offset aperture loses a *varying* fraction of the flux. A
        source that cannot be found in its box keeps its predicted position rather than
        jumping onto a neighbor — the silent lie we want to avoid.
        """
        if not self.recenter:
            return positions
        from photutils.centroids import centroid_quadratic

        boite = max(3.0, 2.0 * float(self.aperture_radius))
        height, width = plan.shape
        output = positions.astype(float).copy()
        for i, (x, y) in enumerate(positions):
            x0, x1 = int(max(0, x - boite)), int(min(width, x + boite + 1))
            y0, y1 = int(max(0, y - boite)), int(min(height, y + boite + 1))
            if x1 - x0 < 3 or y1 - y0 < 3:
                continue
            try:
                cx, cy = centroid_quadratic(plan[y0:y1, x0:x1])
            except Exception:
                continue
            if np.isfinite(cx) and np.isfinite(cy):
                output[i] = (x0 + cx, y0 + cy)
        return output

    def measure_frame(self, path: str, stars: list[dict]) -> dict:
        """Raw photometry of one frame — the expensive part, the one we cache."""
        from ..io import load_image_array
        from ..io.fits import load_fits_header, observation_airmass, observation_jd

        data = load_image_array(path).astype(np.float32)
        plan = self._plan(data)
        try:
            keywords = load_fits_header(path)
        except Exception:  # a non-FITS image has no header: no date, no filter
            keywords = {}

        positions = self._recentrer(plan, self._positions(path, plan, keywords, stars))
        measure = measure_apertures(plan, positions[:, 0], positions[:, 1],
                                   float(self.aperture_radius), float(self.annulus_inner),
                                   float(self.annulus_outer))
        jd = observation_jd(keywords)
        target = next((i for i, e in enumerate(stars) if e["role"] == "target"), 0)
        return {
            "jd": jd,
            "filter": str(keywords.get("FILTER", "") or ""),
            "airmass": observation_airmass(keywords, jd, stars[target].get("ra"),
                                           stars[target].get("dec")),
            "stars": [
                {"role": stars[i]["role"], "x": float(positions[i, 0]),
                 "y": float(positions[i, 1]), "flux": float(measure["flux"][i]),
                 "flux_error": float(measure["flux_error"][i]),
                 "inside": bool(measure["inside"][i])}
                for i in range(len(stars))
            ],
        }

    def measure_raw(self) -> list[dict]:
        """The measurements alone, without judgement — cached per file."""
        from ..io.fits import celestial_wcs, load_fits_header
        from ..pipeline.measure_cache import PhotometryCache

        stars = self.stars()
        paths = list(self.frames)
        if not paths:
            raise ValueError(_t("LightCurve: no frames given."))

        # The first frame is the reference for the transport: we ask it for its WCS and its
        # plane once and for all, before the loop.
        self._reference = None
        first = paths[0]
        try:
            header = load_fits_header(first)
        except Exception:
            header = {}
        from ..io import load_image_array

        plan_reference = self._plan(load_image_array(first).astype(np.float32))
        self._reference = (first, plan_reference, celestial_wcs(header))

        repo = PhotometryCache() if self.use_cache else None
        settings = {**self.detection_values(), "stars": format_stars(stars)}
        lines = []
        total = len(paths)
        for index, path in enumerate(paths):
            self._checkpoint()
            self._progress(index / max(total, 1), _t("Photometry {n}/{total}").format(
                n=index + 1, total=total))
            line = repo.get(path, settings) if repo is not None else None
            if line is None:
                line = self.measure_frame(path, stars)
                if repo is not None:
                    repo.put(path, settings, line)
            line["frame"] = path
            lines.append(line)
        if repo is not None:
            repo.flush()
        self._progress(1.0, _t("Photometry complete"))
        return lines

    # --- judgement ------------------------------------------------------------------
    def evaluate(self, lines: list[dict]) -> list[dict]:
        """Derives the magnitudes from the raw fluxes — **idempotent**, hence replayable for
        nothing.

        Three modes. ``instrumental`` returns the raw magnitude of the target, useful for
        diagnosis. ``single`` refers it to the first comparison. ``ensemble``, the default,
        refers it to the **sum** of the comparison fluxes, which amounts to a flux-weighted
        average: a faint comparison weighs little, and a comparison that turns out to be
        variable contaminates the result that much less.
        """
        stars = self.stars()
        magnitudes = [e.get("mag") for e in stars if e["role"] == "comparison"]
        connues = [m for m in magnitudes if m is not None]
        # Sum of the catalogue fluxes, to bring the ensemble back to a standard magnitude.
        reference_mag = None
        if connues and len(connues) == len(magnitudes):
            reference_mag = -2.5 * np.log10(sum(10 ** (-0.4 * m) for m in connues))

        points = []
        for line in lines:
            point = {"frame": line.get("frame"), "jd": line.get("jd"),
                     "filter": line.get("filter") or "", "airmass": line.get("airmass")}
            roles = line.get("stars", [])
            target = next((s for s in roles if s["role"] == "target"), None)
            comparaisons = [s for s in roles if s["role"] == "comparison" and s["inside"]]
            controle = next((s for s in roles if s["role"] == "check"), None)
            point["target_flux"] = None if target is None else target["flux"]
            point["target_flux_error"] = None if target is None else target["flux_error"]
            point["comparison_flux"] = sum(s["flux"] for s in comparaisons) or None

            point["mag"], point["mag_err"] = self._magnitude(
                target, comparaisons, reference_mag)
            point["check_mag"], _ = self._magnitude(controle, comparaisons, reference_mag)
            points.append(point)

        points.sort(key=lambda p: (p["jd"] is None, p["jd"] or 0.0))
        self.measurements = points
        return points

    def _magnitude(self, star, comparaisons, reference_mag):
        """Magnitude of a star and its uncertainty, ``(None, None)`` if not measurable."""
        if star is None or not star.get("inside") or star["flux"] <= 0:
            return None, None
        flux = float(star["flux"])
        erreur_relative = (float(star["flux_error"]) / flux) if flux > 0 else 0.0
        if self.mode == "instrumental" or not comparaisons:
            return -2.5 * float(np.log10(flux)), 1.0857 * erreur_relative
        kept_rows = comparaisons if self.mode == "ensemble" else comparaisons[:1]
        total = sum(float(s["flux"]) for s in kept_rows)
        if total <= 0:
            return None, None
        magnitude = -2.5 * float(np.log10(flux / total))
        # The uncertainties of the target and of the ensemble add in quadrature.
        erreur_comp = float(np.sqrt(sum(float(s["flux_error"]) ** 2 for s in kept_rows))) / total
        error = 1.0857 * float(np.sqrt(erreur_relative ** 2 + erreur_comp ** 2))
        if reference_mag is not None:
            magnitude += reference_mag
        return magnitude, error

    def measure(self) -> list[dict]:
        """Measures then judges — the full chain."""
        return self.evaluate(self.measure_raw())

    # --- exports ----------------------------------------------------------------------
    @property
    def standardized(self) -> bool:
        """True if every comparison carries a catalogue magnitude.

        That is what distinguishes ``MTYPE=STD`` from ``MTYPE=DIF`` in the export: announcing
        a standard magnitude without a catalogue reference would be a false declaration.
        """
        magnitudes = [e.get("mag") for e in self.stars() if e["role"] == "comparison"]
        return bool(magnitudes) and all(m is not None for m in magnitudes)

    def export_csv(self, path: str) -> str:
        target = _preparer(path)
        with open(target, "w", encoding="utf-8", newline="") as flux:
            writer = csv.DictWriter(flux, fieldnames=list(COLUMNS), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.measurements)
        return target

    def export_aavso(self, path: str) -> str:
        """Writes the *AAVSO Extended File Format* — the format the AAVSO ingests.

        Unknown fields are ``na`` and not the empty string: the format requires it, and an
        empty column would be read there as a shift.
        """
        from .. import __version__ as version

        target = _preparer(path)
        name = str(self.notes or "").strip() or "TARGET"
        filter = str(self.filter or "").strip()
        type_mag = "STD" if self.standardized else "DIF"
        with open(target, "w", encoding="utf-8", newline="") as flux:
            flux.write(f"#TYPE=EXTENDED\n#OBSCODE={self.obscode or AAVSO_ABSENT}\n")
            flux.write(f"#SOFTWARE=Retina {version}\n#DELIM=,\n#DATE=JD\n#OBSTYPE=CCD\n")
            writer = csv.writer(flux)
            for point in self.measurements:
                if point["mag"] is None or point["jd"] is None:
                    continue  # a frame without date or measurement is not an observation
                writer.writerow([
                    name,
                    f"{point['jd']:.6f}",
                    f"{point['mag']:.4f}",
                    AAVSO_ABSENT if point["mag_err"] is None else f"{point['mag_err']:.4f}",
                    filter or point["filter"] or AAVSO_ABSENT,
                    "NO",  # TRANS: no band transformation applied
                    type_mag,
                    AAVSO_ABSENT,  # CNAME — comparisons are designated by coordinates
                    AAVSO_ABSENT,  # CMAG
                    AAVSO_ABSENT,  # KNAME
                    AAVSO_ABSENT if point["check_mag"] is None
                    else f"{point['check_mag']:.4f}",
                    AAVSO_ABSENT if point["airmass"] is None else f"{point['airmass']:.4f}",
                    AAVSO_ABSENT,  # GROUP
                    str(self.chart or AAVSO_ABSENT),
                    str(self.notes or AAVSO_ABSENT),
                ])
        return target

    def execute_global(self, app) -> bool:
        points = self.measure()
        measures = [p for p in points if p["mag"] is not None]
        self.result = {
            "n_frames": len(points),
            "n_measured": len(measures),
            "columns": list(COLUMNS),
            "points": points,
            "mode": str(self.mode),
            "standardized": self.standardized,
        }
        if self.output_csv:
            self.result["output_csv"] = self.export_csv(str(self.output_csv))
        if self.output_aavso:
            self.result["output_aavso"] = self.export_aavso(str(self.output_aavso))
        return True


def _tuple_to_star(value) -> dict:
    if isinstance(value, dict):
        return value
    values = list(value)
    star = {"ra": float(values[0]), "dec": float(values[1])}
    if len(values) > 2:
        star["mag"] = float(values[2])
    return star


def _preparer(path: str) -> str:
    target = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    return target
