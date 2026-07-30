"""EphemerisGenerator — apparent positions of a solar-system body over time.

For astrometry and the annotation of moving objects: comets, asteroids, planets. A
**measurement** process (read-only): the table (time, RA, Dec, distance) is used to plot a
trajectory.

# Three sources, from the most self-contained to the most precise

1. **`builtin`** — the analytic ERFA theories, inside astropy, without a single byte to
   download. Precision of the order of the arcsecond on the planets: amply enough to annotate
   a field.
2. **`de440s`** — the JPL kernel, downloaded once (~32 MB) by astropy's cache.
   Milliarcsecond. Useful for an occultation, not for an annotation.
3. **`custom`** — any small body, through JPL Horizons: asteroids, comets, probes. It is the
   only route for an object that is not a planet, since neither ERFA nor the DE kernels know
   about small bodies.

The last two go through the network; the first, never. That is why it remains the default: an
annotation process must not depend on a connection.
"""

from __future__ import annotations

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register

#: columns of ``.result['ephemeris']``
COLUMNS = ("time", "ra_deg", "dec_deg", "distance_au")


@register
class EphemerisGenerator(Process):
    process_id = "EphemerisGenerator"
    category = "Astrometry"
    is_global = True
    parameters = [
        Parameter("body", "enum", "mars",
                  choices=("sun", "moon", "mercury", "venus", "mars",
                           "jupiter", "saturn", "uranus", "neptune", "custom"),
                  label=N_("Body")),
        Parameter("custom_id", "str", "", label=N_("Small-body designation"),
                  tooltip=N_("JPL Horizons designation, e.g. 'Ceres', '2024 YR4', '1P/Halley'"),
                  visible_when=("body", ("custom",))),
        # `kernel` and not `ephemeris`: `self.ephemeris` already carries the **produced
        # table**, and a parameter of the same name would have been overwritten by it — to
        # the point where the process asked astropy for a kernel named "[]".
        Parameter("kernel", "enum", "builtin", choices=("builtin", "de440s"),
                  label=N_("Ephemeris kernel"),
                  tooltip=N_("de440s is the JPL kernel: more precise, downloaded once (~32 MB)"),
                  visible_when=("body", ("sun", "moon", "mercury", "venus", "mars",
                                         "jupiter", "saturn", "uranus", "neptune"))),
        Parameter("start", "str", "2026-01-01T00:00:00", label=N_("Start (ISO UTC)")),
        Parameter("step_hours", "real", 24.0, 0.01, 8760.0, label=N_("Step (hours)")),
        Parameter("count", "int", 10, 1, 100000, label=N_("Number of points")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ephemeris: list[dict] = []
        self.result: dict | None = None

    def _instants(self):
        import numpy as np
        from astropy import units as u
        from astropy.time import Time

        return Time(self.start) + np.arange(int(self.count)) * float(self.step_hours) * u.hour

    def generate(self) -> list[dict]:
        rows = (self._minor_body() if self.body == "custom" else self._major_body())
        self.ephemeris = rows
        # `.result` **must** be a dict: `server/jobs.py::_result_de` publishes nothing else,
        # so a table stored elsewhere (or in a list) never made it back to the client.
        # `.ephemeris` stays, for the console and so as not to break any script.
        self.result = {"n_points": len(rows), "columns": list(COLUMNS), "ephemeris": rows}
        return rows

    def _major_body(self) -> list[dict]:
        from astropy import units as u
        from astropy.coordinates import get_body, solar_system_ephemeris

        instants = self._instants()
        with solar_system_ephemeris.set(str(self.kernel)):
            coords = get_body(self.body, instants)
        icrs = coords.icrs
        return [{
            "time": instants[i].isot,
            "ra_deg": float(icrs[i].ra.deg),
            "dec_deg": float(icrs[i].dec.deg),
            "distance_au": float(coords[i].distance.to(u.au).value),
        } for i in range(len(instants))]

    def _minor_body(self) -> list[dict]:
        """Asteroid, comet or probe, through JPL Horizons.

        Horizons is queried **once** with the whole list of instants: one request per point
        would make hundreds of network round trips for a one-month trajectory.
        """
        from astroquery.jplhorizons import Horizons

        if not str(self.custom_id).strip():
            raise ValueError(
                _t("EphemerisGenerator: body='custom' needs a small-body designation."))
        instants = self._instants()
        table = Horizons(id=str(self.custom_id).strip(),
                         epochs=[float(t.jd) for t in instants]).ephemerides()
        return [{
            "time": instants[i].isot,
            "ra_deg": float(table["RA"][i]),
            "dec_deg": float(table["DEC"][i]),
            "distance_au": float(table["delta"][i]),
        } for i in range(len(table))]

    def execute_global(self, app) -> bool:
        self.generate()
        return True
