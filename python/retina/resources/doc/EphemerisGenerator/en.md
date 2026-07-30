---
id: EphemerisGenerator
category: Astrometry
title: Ephemeris Generator
brief: Computes the apparent trajectory (time, RA, Dec, distance) of a solar-system body over a series of instants.
keywords: [ephemeris, astrometry, RA, Dec, solar system, comet, asteroid, trajectory]
related: [Annotation, CatalogAnnotation, PlateSolve, CometAlignment]
icon: calendar-stats
references:
  - "PixInsight — EphemerisGeneration tool reference."
  - "Astropy — astropy.coordinates.get_body and solar_system_ephemeris."
  - "IAU — International Celestial Reference System (ICRS)."
---

## Summary

`EphemerisGenerator` computes, for a chosen solar-system body, a series of evenly spaced
instants and, for each one, its **apparent geocentric position** — right ascension,
declination, and distance from Earth. It is a **global, measurement-only** process (no window
input, no image produced): it reproduces PixInsight's `EphemerisGeneration`, used to plot a
moving object's (comet, asteroid, planet) trajectory on an annotation, or to prepare an
alignment that tracks the object rather than the star field.

## Use cases

- **Plot a trajectory** of a comet or asteroid on an annotated mosaic, to check it matches the
  motion observed between exposures.
- **Prepare a `CometAlignment`**: know the expected nucleus position at each instant of the
  series to guide or verify tracking on the object rather than on the stars.
- **Plan a session**: obtain a planet's RA/Dec at the intended acquisition time to frame the
  field or check its visibility.
- **Cross-check an identification**: confirm that a moving point detected across an image
  series matches the theoretical position of a known body.

## How it works

1. The time series is built from `start` (ISO UTC) with a fixed step `step_hours`, repeated
   `count` times: $t_i = t_0 + i \cdot \Delta t$.
2. For each instant, the position of the chosen body (`body`) is computed with astropy's
   **built-in** ephemeris (`solar_system_ephemeris.set("builtin")`, analytical theories such as
   VSOP87/ELP2000 via ERFA) — **no download** of a JPL ephemeris file is required, unlike
   `PlateSolve` in its online astrometry.net mode.
3. `get_body()` returns the **apparent geocentric position** (corrected for light travel time
   from Earth), expressed in the GCRS frame and then converted to **ICRS** (the international
   celestial reference system, quasi-inertial) to obtain RA/Dec/distance.
4. Each computed row (`time`, `ra_deg`, `dec_deg`, `distance_au`) is accumulated into the
   `self.ephemeris` list, exposed after execution for consumption by the GUI/annotation layer
   or by a script.

## Mathematics

At instant $t_i$, the built-in ephemeris provides the body's geocentric position vector
$\vec r_i = (x_i, y_i, z_i)$ in the ICRS equatorial frame (light-time corrected, Earth fixed at
the origin). Right ascension, declination and distance follow from the Cartesian-to-spherical
conversion:

$$
\alpha_i = \operatorname{atan2}(y_i,\, x_i) \bmod 360°, \qquad
\delta_i = \operatorname{atan2}\!\left(z_i,\, \sqrt{x_i^2 + y_i^2}\right), \qquad
d_i = \lVert \vec r_i \rVert.
$$

The sampled instants form an arithmetic sequence:

$$ t_i = t_0 + i\,\Delta t, \qquad i = 0, \dots, \texttt{count} - 1, \qquad
\Delta t = \texttt{step\_hours} \text{ (hours)}. $$

The distance $d_i$ is expressed in astronomical units (AU, $1\,\text{AU} \approx
1.496 \times 10^8$ km). Accuracy depends on the analytical theory used by astropy's
`"builtin"` backend (VSOP87 for the planets, ELP2000 for the Moon): on the order of a few
arcseconds over the current century, more than enough to plot a trajectory or frame a field,
but **not sufficient for sub-arcsecond plate-solving** (for which PixInsight or `PlateSolve`
rely on real astrometric data rather than an analytical theory).

## Parameters

- **`body`** — *enum*, default `mars`, choices `sun`, `moon`, `mercury`, `venus`, `mars`,
  `jupiter`, `saturn`, `uranus`, `neptune`. The solar-system body whose trajectory is computed.
  Comets and asteroids are **not** in this list (the built-in ephemeris only covers major
  bodies); for a small body, compute its positions outside this process and inject them
  manually, or use `CometAlignment` with a trajectory supplied separately.
- **`start`** — *str*, default `2026-01-01T00:00:00`. Starting instant of the series, in ISO
  8601 **UTC** format (e.g. `2026-03-15T22:30:00`). No timezone conversion is performed: always
  supply UTC time.
- **`step_hours`** — *real*, default `24.0`, range `0.01`–`8760`. Time step between two
  consecutive points, in hours. `8760` corresponds to one year; a sub-hourly value suits a
  fast-moving object (a close asteroid, an approaching comet).
- **`count`** — *int*, default `10`, range `1`–`100000`. Number of points computed in the
  series. A large value combined with a fine step can represent significant computation
  (each point queries the analytical ephemeris).

## Tips & pitfalls

> **Warning** — astropy's `"builtin"` ephemeris is **analytical**, not a downloaded JPL DE
> ephemeris: its accuracy (arcseconds) suits annotation and planning, not sub-pixel
> astrometric alignment.

> **Note** — `start` must be strict ISO UTC. A malformed string (timezone included, ambiguous
> format) makes `Time(self.start)` fail on the astropy side.

- The returned position is **apparent geocentric** (as seen from Earth's center, light time
  included) — not topocentric: it ignores parallax due to the observer's location, generally
  negligible except for the Moon or a very close asteroid.
- The result is not an image window: `execute_global()` returns `True` and fills
  `self.ephemeris`, a list of dictionaries `{time, ra_deg, dec_deg, distance_au}` to consume
  from a script or via the GUI annotation.
- To display the trajectory over an image already astrometrically solved (WCS), combine this
  process with `Annotation` or `CatalogAnnotation`.

## See also

- [Annotation](retina-doc://Annotation) — draws an RA/Dec grid or markers on a solved image.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — annotates an image from a source catalog.
- [PlateSolve](retina-doc://PlateSolve) — astrometric resolution (WCS) needed to project a trajectory onto the image.
- [CometAlignment](retina-doc://CometAlignment) — alignment tracking a moving object rather than the star field.

## References

- PixInsight — *EphemerisGeneration* tool reference.
- Astropy — `astropy.coordinates.get_body` and `solar_system_ephemeris`.
- IAU — *International Celestial Reference System (ICRS)*.
