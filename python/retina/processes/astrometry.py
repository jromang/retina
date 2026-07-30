"""Astrometry: plate-solving (Astrometry.net) and annotation (coordinate grid).

`PlateSolve` detects the stars and solves the field through the Astrometry.net API
(astroquery, key required, online); the WCS solution is stored on the window (`window.wcs`).
`Annotation` relies on that WCS to draw an RA/Dec grid over the image.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register
from .stars import detect_sources

#: Tags of the annotation overlays — a replay replaces the previous ones instead of adding to
#: them, and another tool does not erase them while erasing its own.
ANNOTATION_TAG = "annotation"
CATALOG_TAG = "annotation.catalog"

#: Points per grid line. Enough for a curved line to stay curved on screen (a tangential
#: projection is straight only at the centre of the field), few enough for the overlay to stay
#: light.
_GRID_SAMPLES = 64
#: Beyond this fraction of the diagonal, two consecutive points are not on the same line: they
#: straddle a discontinuity (prime meridian, pole) and joining them would draw a stroke right
#: across the image.
_JUMP_FRACTION = 0.25


def synthetic_tan(ra_deg: float, dec_deg: float, fov_deg: float, size: int):
    """Synthetic TAN WCS centred on (ra, dec), covering ``fov_deg`` over ``size`` pixels.

    Shared by the finding chart and the mosaic planner. Laying the tiles out in this
    **tangent plane** rather than in RA/Dec arithmetic is what avoids the two classic traps:
    the convergence of the meridians (a constant step in RA shrinks as cos δ) and the passage
    through the pole, where the very notion of a "step in RA" ceases to make sense.
    """
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crval = [float(ra_deg), float(dec_deg)]
    wcs.wcs.crpix = [size / 2.0, size / 2.0]
    # RA increases towards the LEFT (sky-chart convention), Dec upwards; the y-down image
    # convention forces the negative sign on Dec here.
    wcs.wcs.cdelt = [float(fov_deg) / size, -float(fov_deg) / size]
    return wcs


def _grid_polylines(wcs, width: int, height: int, spacing: float):
    """Iso-RA and iso-Dec of the field, as polylines of **image** coordinates, plus labels.

    Sampled in **world** coordinates then projected, and not detected pixel by pixel the way
    the burnt-in mode does: that is what yields vectors, hence a grid that stays thin at every
    zoom level instead of being a frozen pixel thickness.

    Two discontinuities are handled. The **prime meridian**: a field straddling RA=0 yields
    values that jump from 359 to 1, of which we cannot take the min and the max — hence the
    "unwrapping". And the **projection jumps**: a line whose two consecutive points land at
    opposite ends of the image is cut into two segments rather than joined.
    """
    coins_x = [0, width - 1, 0, width - 1, width // 2, width // 2, 0, width - 1]
    coins_y = [0, 0, height - 1, height - 1, 0, height - 1, height // 2, height // 2]
    sky = wcs.pixel_to_world(np.array(coins_x, dtype=float), np.array(coins_y, dtype=float))
    ras = np.asarray(sky.ra.deg, dtype=float)
    decs = np.asarray(sky.dec.deg, dtype=float)
    if not np.all(np.isfinite(ras)) or not np.all(np.isfinite(decs)):
        return [], []

    # Unwrapping: if the apparent extent exceeds half a turn, the field straddles RA=0.
    if ras.max() - ras.min() > 180.0:
        ras = np.where(ras < 180.0, ras + 360.0, ras)
    ra0, ra1 = ras.min(), ras.max()
    dec0, dec1 = max(decs.min(), -89.999), min(decs.max(), 89.999)

    saut = _JUMP_FRACTION * float(np.hypot(width, height))
    segments: list[list[list[float]]] = []
    label_texts: list[dict] = []

    def _tracer(fixed_values, samples, iso_ra: bool, format_etiquette) -> None:
        for fixe in fixed_values:
            if iso_ra:
                monde_ra = np.full_like(samples, fixe)
                monde_dec = samples
            else:
                monde_ra = samples
                monde_dec = np.full_like(samples, fixe)
            xs, ys = wcs.world_to_pixel_values(monde_ra % 360.0, monde_dec)
            current: list[list[float]] = []
            previous: tuple[float, float] | None = None
            for x, y in zip(np.atleast_1d(xs), np.atleast_1d(ys), strict=True):
                x, y = float(x), float(y)
                inside = (np.isfinite(x) and np.isfinite(y)
                          and -width <= x <= 2 * width and -height <= y <= 2 * height)
                rupture = previous is not None and (
                    np.hypot(x - previous[0], y - previous[1]) > saut
                )
                if not inside or rupture:
                    if len(current) >= 2:
                        segments.append(current)
                    current = []
                    previous = None
                    if not inside:
                        continue
                current.append([x, y])
                previous = (x, y)
            if len(current) >= 2:
                segments.append(current)
            # Label at the first point genuinely inside the image, if there is one: a label
            # placed off-field would not be visible, and placing one per line would cost
            # dozens of invisible texts.
            for point in (p for seg in segments[-2:] for p in seg):
                if 4 <= point[0] <= width - 30 and 12 <= point[1] <= height - 4:
                    label_texts.append({"x": point[0] + 3, "y": point[1] - 3,
                                       "text": format_etiquette(fixe)})
                    break

    dec_echantillons = np.linspace(dec0, dec1, _GRID_SAMPLES)
    ra_echantillons = np.linspace(ra0, ra1, _GRID_SAMPLES)
    start_ra = np.ceil(ra0 / spacing) * spacing
    start_dec = np.ceil(dec0 / spacing) * spacing
    _tracer(np.arange(start_ra, ra1 + 1e-9, spacing), dec_echantillons, True,
            lambda v: f"{(v % 360.0) / 15.0:.2f}h")
    _tracer(np.arange(start_dec, dec1 + 1e-9, spacing), ra_echantillons, False,
            lambda v: f"{v:+.2f}°")
    return segments, label_texts


@register
class PlateSolve(Process):
    """Astrometric solution. Stores the WCS on the window (does not modify the pixels).

    Backends:
    - ``auto`` (default): picks according to the platform — **ASTAP on Windows**, otherwise
      the Python ``astrometry`` solver (the offline pip package builds natively on Linux).
    - ``astrometry``: OFFLINE, pure Python (astrometry.net indexes downloaded on 1st call).
    - ``astrometry_net``: ONLINE, API key required.
    - ``astap``: native ASTAP executable (bundled in ``vendor/astap/``, offline star database).
      ASTAP does its own star extraction → it works directly on the image.
    """

    process_id = "PlateSolve"
    category = "Astrometry"
    supports_realtime = False  # astrometric solution: seconds to minutes
    parameters = [
        Parameter("backend", "enum", "auto",
                  choices=("auto", "astrometry", "astrometry_net", "astap"), label=N_("Backend")),
        # --- offline backend (astrometry) ---
        # 4200 (Tycho-2) is on data.astrometry.net (reliable); 5200 (Gaia) is on nersc
        Parameter("series", "enum", "4200",
                  choices=("4100", "4200", "5000", "5200", "5200_heavy", "6000", "6100"),
                  label=N_("Index series")),
        # index scales, to be matched to the field (FOV): [8-11] ≈ fields ~30-120' (1.5°)
        Parameter("scales", "intlist", default=[8, 9, 10, 11], label=N_("Index scales")),
        Parameter("cache_dir", "path", "", label=N_("Index directory (offline)")),
        Parameter("ra", "real", 0.0, 0.0, 360.0, label=N_("Approximate RA (deg, 0 = blind)")),
        Parameter("dec", "real", 0.0, -90.0, 90.0, label=N_("Approximate Dec (deg)")),
        Parameter("radius", "real", 0.0, 0.0, 180.0,
                  label=N_("Search radius (deg, 0 = blind)")),
        # --- common: image scale ---
        Parameter("scale_low", "real", 0.0, 0.0, 3600.0, label=N_("Min scale (arcsec/px)")),
        Parameter("scale_high", "real", 0.0, 0.0, 3600.0, label=N_("Max scale (arcsec/px)")),
        # number of stars sent to the solver: too many → combinatorial explosion (slow)
        Parameter("max_stars", "int", 100, 10, 1000, label=N_("Max stars (solver)")),
        # --- online backend (astrometry_net) ---
        Parameter("api_key", "str", "", label=N_("Astrometry.net API key (online)")),
        Parameter("timeout", "int", 120, 30, 1200, label=N_("Timeout (s)")),
        # --- ASTAP backend (native executable) ---
        Parameter("astap_exe", "path", "", label=N_("astap_cli path (empty = bundle/PATH)")),
    ]

    def execute_on(self, view) -> bool:  # read: stores the WCS, does not modify the pixels
        if view.window is None:
            raise ValueError(_t("PlateSolve: the view does not belong to any window."))
        view.window.wcs = self.solve(view)
        return True

    def solve(self, target) -> object:
        """Solves ``target`` (a :class:`View` or an :class:`Image`) and returns its WCS.

        Separated from :meth:`execute_on` so that preprocessing, which works file to file and
        has no window at hand, can solve an integration and write the solution into its
        header.
        """
        backend = self._resolve_backend()
        if backend == "astap":
            # ASTAP does its own extraction: it works on the image, not on a list.
            return self._solve_astap(target)
        stars_xy, w, h = self._detect_stars(target)
        if backend == "astrometry_net":
            return self._solve_online(stars_xy, w, h)
        return self._solve_offline(stars_xy)

    def _resolve_backend(self) -> str:
        """``auto`` → ASTAP on Windows, otherwise the Python ``astrometry`` solver."""
        import sys

        if self.backend == "auto":
            return "astap" if sys.platform == "win32" else "astrometry"
        return self.backend

    @staticmethod
    def _pixels(target) -> np.ndarray:
        """Accepts a :class:`View` (which carries an image) or a bare :class:`Image`."""
        image = getattr(target, "image", target)
        return image.data

    def _detect_stars(self, view):
        lum = self._pixels(view).mean(axis=2)
        sources = detect_sources(lum, fwhm=3.0, threshold_sigma=5.0)
        if sources is None or len(sources) < 10:
            raise ValueError(_t("PlateSolve: not enough stars detected."))
        sources.sort("flux", reverse=True)
        xcol = "xcentroid" if "xcentroid" in sources.colnames else "x_centroid"
        ycol = "ycentroid" if "ycentroid" in sources.colnames else "y_centroid"
        h, w = lum.shape
        xy = [(float(s[xcol]), float(s[ycol])) for s in sources[: int(self.max_stars)]]
        return xy, w, h

    def _solve_offline(self, stars_xy):
        import os

        import astrometry

        from ..paths import cache_path

        # Same location as before in the common case (``~/.cache/retina/…``), but
        # ``XDG_CACHE_HOME`` is now honoured: several hundred megabytes of indexes have no
        # business sitting in a directory the user has moved.
        cache = self.cache_dir or str(cache_path("astrometry-indexes"))
        os.makedirs(cache, exist_ok=True)
        series = getattr(astrometry, f"series_{self.series}")
        # downloads the missing indexes on the 1st call, then 100 % offline
        index_files = series.index_files(
            cache_directory=cache, scales=set(self.scales) if self.scales else None
        )
        solver = astrometry.Solver(index_files)
        size_hint = None
        if self.scale_low > 0 and self.scale_high > 0:
            size_hint = astrometry.SizeHint(
                lower_arcsec_per_pixel=self.scale_low, upper_arcsec_per_pixel=self.scale_high
            )
        position_hint = None
        if self.radius > 0:
            position_hint = astrometry.PositionHint(
                ra_deg=self.ra, dec_deg=self.dec, radius_deg=self.radius
            )
        solution = solver.solve(
            stars=stars_xy, size_hint=size_hint, position_hint=position_hint,
            solution_parameters=astrometry.SolutionParameters(),
        )
        if not solution.has_match():
            raise RuntimeError(_t("PlateSolve (offline): no match found (check scales/indexes)."))
        return solution.best_match().astropy_wcs()

    def _solve_online(self, stars_xy, w, h):
        from astropy.wcs import WCS
        from astroquery.astrometry_net import AstrometryNet

        if not self.api_key:
            raise ValueError(
                _t("PlateSolve (astrometry_net): API key required (api_key parameter)."))
        ast = AstrometryNet()
        ast.api_key = self.api_key
        xs = [p[0] for p in stars_xy]
        ys = [p[1] for p in stars_xy]
        kwargs = {"solve_timeout": int(self.timeout)}
        if self.scale_low > 0 and self.scale_high > 0:
            kwargs.update(scale_units="arcsecperpix", scale_lower=self.scale_low,
                          scale_upper=self.scale_high)
        header = ast.solve_from_source_list(xs, ys, w, h, **kwargs)
        if not header:
            raise RuntimeError(_t("PlateSolve: Astrometry.net did not solve the field."))
        return WCS(header)

    # ------------------------------------------------------------------ ASTAP
    def _solve_astap(self, view):
        """Solves through the ASTAP executable (Windows bundle). ASTAP reads a FITS, detects
        the stars itself, and writes a ``.ini`` (PLTSOLVD + CD matrix) + a ``.wcs``."""
        import os
        import shutil
        import subprocess
        import tempfile

        from astropy.io import fits as _fits

        exe = self._find_astap()
        if exe is None:
            raise RuntimeError(_t(
                "PlateSolve (astap): astap_cli not found. Expected in vendor/astap/, "
                "via $RETINA_ASTAP, the astap_exe parameter, or the PATH."
            ))

        data = self._pixels(view)
        lum = data.mean(axis=2) if data.ndim == 3 else data

        from ..preferences import temp_root

        tmpdir = tempfile.mkdtemp(prefix="retina_astap_", dir=temp_root())
        try:
            img_path = os.path.join(tmpdir, "field.fits")
            _fits.writeto(img_path, np.asarray(lum, dtype=np.float32), overwrite=True)
            base = os.path.join(tmpdir, "field")

            # -fov 0 = ASTAP determines the scale itself (sweep). MUCH more robust than
            # imposing a scale on it: a value that is even slightly wrong makes quad matching
            # fail, whereas the auto mode finds the right scale.
            cmd = [exe, "-f", img_path, "-o", base, "-fov", "0", "-z", "0"]
            if self.radius > 0:  # position hint (speeds it up): RA in hours, SPD = dec + 90
                cmd += ["-r", f"{self.radius:.3f}",
                        "-ra", f"{self.ra / 15.0:.6f}", "-spd", f"{self.dec + 90.0:.6f}"]
            db_dir = self._astap_db_dir(exe)
            if db_dir:
                cmd += ["-d", db_dir]

            proc = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=int(self.timeout), check=False)

            # ASTAP writes a key=value .ini (PLTSOLVD + CRVAL/CRPIX + CD matrix).
            ini_path = base + ".ini"
            kv = self._parse_astap_ini(ini_path) if os.path.exists(ini_path) else {}
            if not kv.get("PLTSOLVD", "").strip().upper().startswith("T"):
                detail = kv.get("ERROR") or kv.get("WARNING") or (proc.stdout or "").strip()[-400:]
                raise RuntimeError(
                    _t("PlateSolve (astap): field not solved — {detail}").format(
                        detail=detail or _t("no solution"))
                )
            return self._wcs_from_astap_ini(kv)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def _parse_astap_ini(path: str) -> dict:
        kv: dict[str, str] = {}
        with open(path, encoding="latin-1") as fh:
            for line in fh:
                if "=" in line:
                    k, _, v = line.partition("=")
                    kv[k.strip().upper()] = v.strip()
        return kv

    @staticmethod
    def _wcs_from_astap_ini(kv: dict):
        """Builds a TAN WCS from the keys of the ASTAP .ini (CRVAL/CRPIX + CD matrix).

        We favour the CD matrix when present and do NOT also add CDELT/CROTA (astropy warns
        about the CD ⊕ CDELT redundancy)."""
        from astropy.io import fits as _fits
        from astropy.wcs import WCS

        def num(key):
            try:
                return float(kv[key])
            except (KeyError, ValueError):
                return None

        hdr = _fits.Header()
        hdr["CTYPE1"], hdr["CTYPE2"] = "RA---TAN", "DEC--TAN"
        for key in ("CRPIX1", "CRPIX2", "CRVAL1", "CRVAL2"):
            v = num(key)
            if v is None:
                raise RuntimeError(_t("PlateSolve (astap): .ini solved but incomplete WCS."))
            hdr[key] = v

        cd = {k: num(k) for k in ("CD1_1", "CD1_2", "CD2_1", "CD2_2")}
        if all(v is not None for v in cd.values()):
            hdr.update(cd)
        else:  # fallback: scale + rotation
            for key in ("CDELT1", "CDELT2", "CROTA1", "CROTA2"):
                v = num(key)
                if v is not None:
                    hdr[key] = v
        return WCS(hdr)

    def _find_astap(self):
        """Locates astap_cli: explicit parameter → $RETINA_ASTAP → vendor bundle → PATH."""
        import os
        import shutil
        import sys

        if self.astap_exe and os.path.exists(self.astap_exe):
            return self.astap_exe
        env = os.environ.get("RETINA_ASTAP")
        if env and os.path.exists(env):
            return env

        subdir = {"win32": "win64", "darwin": "macos"}.get(sys.platform, "linux")
        exe_name = "astap_cli.exe" if sys.platform == "win32" else "astap_cli"
        pkg_dir = os.path.dirname(os.path.dirname(__file__))  # .../retina
        # repository: <root>/python/retina → <root>
        root = os.path.dirname(os.path.dirname(pkg_dir))
        for cand in (
            # repository / editable: <root>/vendor/astap/<platform>/
            os.path.join(root, "vendor", "astap", subdir, exe_name),
            # briefcase bundle: the 'vendor/astap' source is copied next to the retina package
            os.path.join(os.path.dirname(pkg_dir), "astap", subdir, exe_name),
        ):
            if os.path.exists(cand):
                return os.path.abspath(cand)
        return shutil.which("astap_cli") or shutil.which("astap")

    @staticmethod
    def _astap_db_dir(exe: str):
        """Directory of the star database: we assume it is extracted next to the exe."""
        import glob
        import os

        d = os.path.dirname(os.path.abspath(exe))
        # ASTAP database files are .290/.1476 (e.g. d05*.290)
        if glob.glob(os.path.join(d, "*.290")) or glob.glob(os.path.join(d, "*.1476")):
            return d
        return None


@register
class Annotation(Process):
    process_id = "Annotation"
    category = "Astrometry"
    supports_realtime = False  # catalogue query
    parameters = [
        Parameter("grid_spacing", "real", 0.5, 0.001, 90.0, label=N_("Grid spacing (deg)")),
        Parameter("line_width", "real", 0.02, 0.001, 0.2, label=N_("Line width (frac.)")),
        Parameter("render_mode", "enum", "overlay", choices=("overlay", "pixels"),
                  label=N_("Rendering")),
    ]

    def execute_on(self, view) -> bool:
        win = view.window
        if win is None or win.wcs is None:
            raise ValueError(_t("Annotation requires an astrometric solution (run PlateSolve)."))
        if self.render_mode == "overlay":
            return self._draw_overlay(view, win)
        return self._burn_pixels(view, win)

    def _draw_overlay(self, view, win) -> bool:
        """Grid as a vector overlay: nothing is burnt in, hence nothing to undo.

        No ``begin_process``/``end_process``: the pixels do not change, and pushing a history
        entry for a display annotation would suggest that a Ctrl+Z is needed to get the image
        back intact.
        """
        h, w = view.image.data.shape[:2]
        lines, label_texts = _grid_polylines(win.wcs, w, h, float(self.grid_spacing))
        overlays: list[dict] = []
        if lines:
            overlays.append({"kind": "lines", "segments": lines,
                             "color": (0.0, 1.0, 0.4, 0.75), "width": 1.0})
        if label_texts:
            overlays.append({"kind": "text", "items": label_texts,
                             "color": (0.0, 1.0, 0.4, 0.9), "size": 11})
        win.viewport.set_overlays(ANNOTATION_TAG, overlays)
        return True

    def _burn_pixels(self, view, win) -> bool:
        data = view.image.data
        h, w = data.shape[:2]
        ys, xs = np.mgrid[0:h, 0:w]
        sky = win.wcs.pixel_to_world(xs.ravel(), ys.ravel())
        ra = np.asarray(sky.ra.deg).reshape(h, w)
        dec = np.asarray(sky.dec.deg).reshape(h, w)

        sp = float(self.grid_spacing)
        grid = np.zeros((h, w), dtype=bool)
        for coord in (ra, dec):
            frac = np.abs(coord / sp - np.round(coord / sp))
            grid |= frac < self.line_width

        out = np.repeat(data, 3, axis=2) if data.shape[2] == 1 else data.copy()
        out[grid] = np.array([0.0, 1.0, 0.0], dtype=np.float32)  # green grid

        view.begin_process(self.process_id, process=self)
        view.set_image(view.image.with_data(out))
        view.end_process()
        return True


def _gaia_cone(ra: float, dec: float, radius_deg: float,
               limit_mag: float, max_objects: int) -> list[tuple[float, float, float]]:
    """The N BRIGHTEST stars of a Gaia DR3 cone — shared by ``CatalogAnnotation`` and
    ``FindingChart``.

    ADQL rather than ``cone_search``: the latter is limited to the 50 nearest to the centre,
    which misses the bright stars at the periphery.
    """
    from astroquery.gaia import Gaia

    query = (
        f"SELECT TOP {int(max_objects)} ra, dec, phot_g_mean_mag "
        f"FROM gaiadr3.gaia_source "
        f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {float(ra)}, {float(dec)}, {float(radius_deg)})) "
        f"AND phot_g_mean_mag <= {float(limit_mag)} "
        f"ORDER BY phot_g_mean_mag ASC"
    )
    rows = Gaia.launch_job_async(query).get_results()
    return [
        (float(r["ra"]), float(r["dec"]), float(r["phot_g_mean_mag"]))
        for r in rows
        if r["phot_g_mean_mag"] is not None
    ]


@register
class CatalogAnnotation(Process):
    """Overlays the objects of a catalogue (Gaia DR3) through the WCS: markers + magnitudes.

    Requires an astrometric solution (PlateSolve). Headless or in tests, a catalogue can be
    supplied directly through ``set_objects([(ra_deg, dec_deg, mag), …])``.
    """

    process_id = "CatalogAnnotation"
    category = "Astrometry"
    supports_realtime = False  # catalogue query
    parameters = [
        Parameter("catalog", "enum", "gaia", choices=("gaia",), label=N_("Catalog")),
        Parameter("limit_mag", "real", 12.0, -5.0, 25.0, label=N_("Limiting magnitude")),
        Parameter("max_objects", "int", 300, 1, 5000, label=N_("Max objects")),
        Parameter("marker_radius", "real", 6.0, 1.0, 50.0, label=N_("Marker radius (px)")),
        Parameter("labels", "bool", True, label=N_("Labels (magnitude)")),
        Parameter("render_mode", "enum", "overlay", choices=("overlay", "pixels"),
                  label=N_("Rendering")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._objects = None  # catalogue supplied explicitly (ra, dec, mag)
        self.count = 0

    def set_objects(self, objects) -> CatalogAnnotation:
        self._objects = list(objects)
        return self

    def _query_gaia(self, win):
        h, w = win.main_view.image.data.shape[:2]
        center = win.wcs.pixel_to_world(w / 2, h / 2)
        radius = min(center.separation(win.wcs.pixel_to_world(0, 0)).deg, 2.0)
        return _gaia_cone(center.ra.deg, center.dec.deg, radius,
                          float(self.limit_mag), int(self.max_objects))

    def execute_on(self, view) -> bool:
        win = view.window
        if win is None or win.wcs is None:
            raise ValueError(_t("CatalogAnnotation requires a WCS (run PlateSolve)."))

        objs = self._objects if self._objects is not None else self._query_gaia(win)
        if self.render_mode == "overlay":
            return self._draw_overlay(view, win, objs)
        return self._burn_pixels(view, win, objs)

    def _draw_overlay(self, view, win, objs) -> bool:
        """Markers and magnitudes as an overlay — the image stays the one we measured."""
        h, w = view.image.data.shape[:2]
        r = float(self.marker_radius)
        cercles: list[dict] = []
        texts: list[dict] = []
        self.count = 0
        if objs:
            ras = np.array([o[0] for o in objs], dtype=float)
            decs = np.array([o[1] for o in objs], dtype=float)
            xs, ys = win.wcs.world_to_pixel_values(ras, decs)
            for x, y, obj in zip(np.atleast_1d(xs), np.atleast_1d(ys), objs, strict=True):
                if not (0 <= x < w and 0 <= y < h):
                    continue
                # Ellipses with equal radii: the marker then follows the zoom, where a
                # burnt-in circle kept its pixel size whatever the magnification.
                cercles.append({"x": float(x), "y": float(y), "rx": r, "ry": r, "theta": 0.0})
                if self.labels:
                    texts.append({"x": float(x) + r + 1.0, "y": float(y) - r,
                                   "text": f"{obj[2]:.1f}"})
                self.count += 1
        overlays: list[dict] = []
        if cercles:
            overlays.append({"kind": "ellipses", "items": cercles,
                             "color": (1.0, 1.0, 0.0, 0.85), "width": 1.0})
        if texts:
            overlays.append({"kind": "text", "items": texts,
                             "color": (1.0, 1.0, 0.0, 0.9), "size": 11})
        win.viewport.set_overlays(CATALOG_TAG, overlays)
        return True

    def _burn_pixels(self, view, win, objs) -> bool:
        data = view.image.data
        h, w = data.shape[:2]

        from PIL import Image as PILImage
        from PIL import ImageDraw

        rgb = np.repeat(data, 3, axis=2) if data.shape[2] == 1 else data[:, :, :3]
        disp = (np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8)
        pim = PILImage.fromarray(disp)
        draw = ImageDraw.Draw(pim)

        r = float(self.marker_radius)
        self.count = 0
        if objs:
            ras = np.array([o[0] for o in objs])
            decs = np.array([o[1] for o in objs])
            xs, ys = win.wcs.world_to_pixel_values(ras, decs)
            for (x, y, obj) in zip(xs, ys, objs, strict=True):
                if 0 <= x < w and 0 <= y < h:
                    draw.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 0))
                    if self.labels:
                        draw.text((x + r + 1, y - r), f"{obj[2]:.1f}", fill=(255, 255, 0))
                    self.count += 1

        out = (np.asarray(pim).astype(np.float32) / 255.0)
        view.begin_process(self.process_id, process=self)
        view.set_image(view.image.with_data(out))
        view.end_process()
        return True


@register
class FindingChart(Process):
    """Synthetic finding chart built from a WCS.

    A **global** process: it produces a new window — the chart — without touching the pixels
    of the source. The chart is a synthetic sky centred on the field of the target window:
    RA/Dec grid (reuses ``_grid_polylines``), footprint of the field (the projected corners of
    the image), catalogue stars as discs proportional to magnitude, central marker and
    cardinal points. The chart's WCS is a synthetic north-up TAN; drawing through PIL, like
    the burnt-in mode of ``CatalogAnnotation``.

    Headless or in tests, ``set_objects([(ra, dec, mag), …])`` avoids the network query.
    """

    process_id = "FindingChart"
    category = "Astrometry"
    is_global = True
    supports_realtime = False
    parameters = [
        Parameter("view_id", "str", "", label=N_("Source window (empty = active)")),
        Parameter("size", "int", 800, 128, 4096, label=N_("Chart size (px)")),
        Parameter("field_factor", "real", 3.0, 1.1, 20.0, label=N_("Field factor")),
        Parameter("grid_spacing", "real", 0.0, 0.0, 90.0,
                  label=N_("Grid spacing (deg, 0 = auto)")),
        Parameter("catalog", "enum", "none", choices=("none", "gaia"), label=N_("Catalog")),
        Parameter("limit_mag", "real", 9.0, -5.0, 25.0, label=N_("Limiting magnitude")),
        Parameter("max_objects", "int", 300, 1, 5000, label=N_("Max objects")),
        Parameter("new_image_id", "str", "", label=N_("New image id")),
    ]

    #: "round" steps offered for the automatic grid (degrees)
    _NICE_SPACINGS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 45.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._objects = None  # catalogue supplied explicitly (ra, dec, mag)

    def set_objects(self, objects) -> FindingChart:
        self._objects = list(objects)
        return self

    def execute_global(self, app) -> bool:
        win = None
        if self.view_id:
            win = next((w for w in app.windows
                        if w.id == self.view_id or w.main_view.id == self.view_id), None)
            if win is None:
                raise ValueError(
                    _t("Window not found: {view_id!r}").format(view_id=self.view_id))
        else:
            win = app.active_window
        if win is None or win.wcs is None:
            raise ValueError(
                _t("FindingChart requires an astrometric solution (run PlateSolve).")
            )

        chart_wcs, fov_deg = self._chart_wcs(win)
        objs = self._objects
        if objs is None and self.catalog == "gaia":
            h, w = win.main_view.image.data.shape[:2]
            center = win.wcs.pixel_to_world(w / 2, h / 2)
            objs = _gaia_cone(center.ra.deg, center.dec.deg, min(fov_deg / 2, 5.0),
                              float(self.limit_mag), int(self.max_objects))
        data = self.render(chart_wcs, win, objs or [])

        from ..model.image import Image

        chart = app.new_window(Image(data), window_id=self.new_image_id
                               or f"{win.id}_FindingChart")
        chart.wcs = chart_wcs  # the chart is itself solved: immediate celestial readout
        return True

    # --- geometry ----------------------------------------------------------------
    def _chart_wcs(self, win):
        """Synthetic TAN WCS: centre of the source field, north up, east left."""
        h, w = win.main_view.image.data.shape[:2]
        center = win.wcs.pixel_to_world(w / 2, h / 2)
        # diagonal of the source field, in degrees — the chart scale follows from it
        corner = win.wcs.pixel_to_world(0.0, 0.0)
        field_deg = max(2.0 * float(center.separation(corner).deg), 1e-4)
        fov_deg = field_deg * float(self.field_factor)
        return synthetic_tan(float(center.ra.deg), float(center.dec.deg),
                             fov_deg, int(self.size)), fov_deg

    def _auto_spacing(self, fov_deg: float) -> float:
        target = fov_deg / 4.0
        for pas in self._NICE_SPACINGS:
            if pas >= target:
                return pas
        return self._NICE_SPACINGS[-1]

    # --- rendering ------------------------------------------------------------
    def render(self, chart_wcs, win, objs) -> np.ndarray:
        """Draws the chart — pure (no app access), directly testable and scriptable."""
        from PIL import Image as PILImage
        from PIL import ImageDraw

        size = int(self.size)
        fov_deg = abs(float(chart_wcs.wcs.cdelt[0])) * size
        pim = PILImage.new("RGB", (size, size), (8, 10, 18))
        draw = ImageDraw.Draw(pim)

        # RA/Dec grid — the same tracer as Annotation, on the chart's WCS
        spacing = float(self.grid_spacing) or self._auto_spacing(fov_deg)
        lines, label_texts = _grid_polylines(chart_wcs, size, size, spacing)
        for segment in lines:
            draw.line([tuple(p) for p in segment], fill=(40, 60, 80), width=1)
        for label_text in label_texts:
            draw.text((label_text["x"], label_text["y"]), label_text["text"], fill=(90, 120, 150))

        # stars: disc ∝ magnitude (bright ones large), off-white
        limit = float(self.limit_mag)
        for ra, dec, mag in objs:
            x, y = chart_wcs.world_to_pixel_values(float(ra), float(dec))
            if not (0 <= x < size and 0 <= y < size):
                continue
            r = max(0.8, 1.0 + 0.45 * (limit - float(mag)))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(230, 230, 220))

        # footprint of the source field: its four corners projected onto the chart
        h, w = win.main_view.image.data.shape[:2]
        sky_corners = win.wcs.pixel_to_world(
            np.array([0.0, w - 1.0, w - 1.0, 0.0]), np.array([0.0, 0.0, h - 1.0, h - 1.0])
        )
        xs, ys = chart_wcs.world_to_pixel_values(
            np.asarray(sky_corners.ra.deg), np.asarray(sky_corners.dec.deg)
        )
        contour = [(float(x), float(y)) for x, y in zip(xs, ys, strict=True)]
        draw.polygon(contour, outline=(255, 190, 60))

        # central marker + cardinal points (north up, east left by construction)
        c = size / 2.0
        draw.line([(c - 12, c), (c - 4, c)], fill=(255, 80, 80), width=1)
        draw.line([(c + 4, c), (c + 12, c)], fill=(255, 80, 80), width=1)
        draw.line([(c, c - 12), (c, c - 4)], fill=(255, 80, 80), width=1)
        draw.line([(c, c + 4), (c, c + 12)], fill=(255, 80, 80), width=1)
        draw.text((c - 3, 4), "N", fill=(200, 200, 210))
        draw.text((6, c - 6), "E", fill=(200, 200, 210))

        return np.asarray(pim).astype(np.float32) / 255.0
