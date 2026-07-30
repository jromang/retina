"""Star catalog access (Gaia, APASS) — measurement processes, read-only.

They query a catalog for the field covered by the view's WCS (``PlateSolve``), project the
stars into pixels and store the list in ``.result``. The basis for annotation, photometric
calibration or the selection of reference stars. Online through ``astroquery``;
``set_catalog(...)`` injects an explicit catalog (headless tests, offline cache).
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


class _CatalogQuery(Process):
    """Shared base: projects a catalog (ra, dec, mag) into the view's WCS field."""

    category = "Global"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._catalog = None  # (ra, dec, mag) list supplied explicitly
        self.result: dict | None = None

    def set_catalog(self, objects):
        """Injects a catalog ``[(ra, dec, mag), …]`` (bypasses the network query)."""
        self._catalog = [tuple(o) for o in objects]
        return self

    def _query(self, win):  # to be implemented by the subclasses
        raise NotImplementedError

    def measure(self, view) -> dict:
        win = view.window
        if win is None or getattr(win, "wcs", None) is None:
            raise ValueError(_t("{process_id} requires a WCS (run PlateSolve).").format(
                process_id=self.process_id))
        cat = self._catalog if self._catalog is not None else self._query(win)
        data = view.image.data
        h, w = data.shape[:2]
        if not cat:
            self.result = {"n_stars": 0, "stars": []}
            return self.result
        ras = np.array([o[0] for o in cat], dtype=np.float64)
        decs = np.array([o[1] for o in cat], dtype=np.float64)
        mags = np.array([o[2] for o in cat], dtype=np.float64)
        xs, ys = win.wcs.world_to_pixel_values(ras, decs)
        inb = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        stars = [
            {"ra": float(ras[i]), "dec": float(decs[i]), "mag": float(mags[i]),
             "x": float(xs[i]), "y": float(ys[i])}
            for i in np.where(inb)[0]
        ]
        self.result = {"n_stars": len(stars), "stars": stars}
        return self.result

    def execute_on(self, view) -> bool:  # read-only: no history entry
        self.measure(view)
        return True

    def execute_on_image(self, image):
        raise NotImplementedError(
            _t("{process_id} requires a view with a WCS: execute_on(view).").format(
                process_id=self.process_id))


@register
class GaiaCatalog(_CatalogQuery):
    """Queries Gaia DR3 for the stars in the field (through ``astroquery.gaia``).

    ``mag_limit`` = limiting G magnitude; ``max_stars`` bounds the count. Result in
    ``.result`` (ra, dec, G mag, x, y in pixels).
    """

    process_id = "GaiaCatalog"
    parameters = [
        Parameter("mag_limit", "real", 16.0, 0.0, 22.0, label=N_("G magnitude limit")),
        Parameter("max_stars", "int", 1000, 1, 100000, label=N_("Maximum stars")),
    ]

    def _query(self, win):
        from astroquery.gaia import Gaia

        h, w = win.main_view.image.data.shape[:2]
        center = win.wcs.pixel_to_world(w / 2, h / 2)
        radius = min(center.separation(win.wcs.pixel_to_world(0, 0)).deg, 3.0)
        query = (
            f"SELECT TOP {int(self.max_stars)} ra, dec, phot_g_mean_mag "
            f"FROM gaiadr3.gaia_source "
            f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {center.ra.deg}, {center.dec.deg}, {radius})) "
            f"AND phot_g_mean_mag < {self.mag_limit}"
        )
        rows = Gaia.launch_job_async(query).get_results()
        return [(float(r["ra"]), float(r["dec"]), float(r["phot_g_mean_mag"])) for r in rows]


@register
class APASSCatalog(_CatalogQuery):
    """Queries APASS DR9 (Vizier ``II/336``) for the stars in the field.

    A photometric catalog (BVgri) useful for color calibration with broadband instruments.
    ``mag_limit`` = limiting V magnitude. Result in ``.result``.
    """

    process_id = "APASSCatalog"
    parameters = [
        Parameter("mag_limit", "real", 16.0, 0.0, 22.0, label=N_("V magnitude limit")),
        Parameter("max_stars", "int", 1000, 1, 100000, label=N_("Maximum stars")),
    ]

    def _query(self, win):
        from astropy.coordinates import SkyCoord
        from astroquery.vizier import Vizier

        h, w = win.main_view.image.data.shape[:2]
        center = win.wcs.pixel_to_world(w / 2, h / 2)
        radius_deg = min(center.separation(win.wcs.pixel_to_world(0, 0)).deg, 3.0)
        viz = Vizier(columns=["RAJ2000", "DEJ2000", "Vmag"],
                     column_filters={"Vmag": f"<{self.mag_limit}"},
                     row_limit=int(self.max_stars))
        coord = SkyCoord(center.ra.deg, center.dec.deg, unit="deg")
        tables = viz.query_region(coord, radius=radius_deg, catalog="II/336")
        if not tables:
            return []
        t = tables[0]
        return [(float(r["RAJ2000"]), float(r["DEJ2000"]), float(r["Vmag"]))
                for r in t if not np.ma.is_masked(r["Vmag"])]


@register
class ConeSearch(Process):
    """Identifies the **named** objects of the field (SIMBAD) — not stars, objects.

    `GaiaCatalog` and `APASSCatalog` return positions and magnitudes; they do not know that one
    of those sources is called M51 and that another is a variable star. That is what SIMBAD
    adds: a **name**, a **type** and a bibliography, which is what is needed to say what was
    photographed — or to find the target of a light curve.

    Read-only. The radius defaults to the view's half-field, bounded: too wide a search would
    return thousands of objects outside the frame, which the projection would then throw away.
    In headless/test use, ``set_objects([...])`` avoids the network query.
    """

    process_id = "ConeSearch"
    category = "Global"
    supports_realtime = False
    parameters = [
        Parameter("radius", "real", 0.0, 0.0, 10.0,
                  label=N_("Search radius (deg, 0 = the field)")),
        Parameter("max_objects", "int", 200, 1, 10000, label=N_("Maximum objects")),
        Parameter("object_types", "str", "", label=N_("Keep only these types"),
                  tooltip=N_("SIMBAD otype prefixes, separated by commas; empty keeps all")),
    ]

    #: columns of ``.result['objects']``
    COLUMNS = ("name", "ra", "dec", "otype", "mag", "x", "y")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._objects = None
        self.result: dict | None = None

    def set_objects(self, rows):
        """Injects a list of dicts ``{name, ra, dec, otype, mag}`` — bypasses the network."""
        self._objects = [dict(r) for r in rows]
        return self

    def _query(self, center_ra: float, center_dec: float, radius_deg: float) -> list[dict]:
        import contextlib

        import astropy.units as u
        from astropy.coordinates import SkyCoord
        from astroquery.simbad import Simbad

        simbad = Simbad()
        # The votable field names changed between astroquery versions; ask for whatever
        # exists rather than failing on a name that has disappeared.
        for field in ("otype", "V"):
            with contextlib.suppress(Exception):
                simbad.add_votable_fields(field)
        table = simbad.query_region(
            SkyCoord(center_ra, center_dec, unit="deg"), radius=radius_deg * u.deg)
        if table is None:
            return []
        return [_simbad_object(line) for line in table[: int(self.max_objects)]]

    def measure(self, view) -> dict:
        win = view.window
        if win is None or getattr(win, "wcs", None) is None:
            raise ValueError(_t("{process_id} requires a WCS (run PlateSolve).").format(
                process_id=self.process_id))
        height, width = view.image.data.shape[:2]
        centre = win.wcs.pixel_to_world(width / 2, height / 2)
        radius = float(self.radius) or min(
            float(centre.separation(win.wcs.pixel_to_world(0, 0)).deg), 5.0)
        objs_ = (self._objects if self._objects is not None
                  else self._query(float(centre.ra.deg), float(centre.dec.deg), radius))

        types = [t.strip() for t in str(self.object_types or "").split(",") if t.strip()]
        kept_items = []
        for obj in objs_:
            if types and not any(str(obj.get("otype", "")).startswith(t) for t in types):
                continue
            x, y = win.wcs.world_to_pixel_values(obj["ra"], obj["dec"])
            x, y = float(np.atleast_1d(x)[0]), float(np.atleast_1d(y)[0])
            if not (0 <= x < width and 0 <= y < height):
                continue
            kept_items.append({**obj, "x": x, "y": y})

        self.result = {"n_objects": len(kept_items), "objects": kept_items,
                       "columns": list(self.COLUMNS)}
        return self.result

    def execute_on(self, view) -> bool:  # read-only
        self.measure(view)
        return True

    def execute_on_image(self, image):
        raise NotImplementedError(
            _t("{process_id} requires a view with a WCS: execute_on(view).").format(
                process_id=self.process_id))


def _simbad_object(line) -> dict:
    """One SIMBAD table row → our dict, whatever the case of the columns.

    astroquery renamed its columns to lowercase (``MAIN_ID`` → ``main_id``) between two
    versions: looking for both prevents an update from silently emptying the name.
    """
    def field(*names):
        for name in names:
            if name in line.colnames:
                value = line[name]
                if not np.ma.is_masked(value):
                    return value
        return None

    magnitude = field("V", "FLUX_V", "flux_v")
    return {
        "name": str(field("main_id", "MAIN_ID") or ""),
        "ra": float(field("ra", "RA_d", "RA") or 0.0),
        "dec": float(field("dec", "DEC_d", "DEC") or 0.0),
        "otype": str(field("otype", "OTYPE") or ""),
        "mag": None if magnitude is None else float(magnitude),
    }
