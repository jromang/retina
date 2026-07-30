---
id: PlateSolve
category: Astrometry
title: Plate Solving (Astrometric Resolution)
brief: Detects the field's stars and solves its astrometric solution (WCS), offline or via the Astrometry.net API.
keywords: [astrometry, plate solving, WCS, astrometry.net, quads, index, RA/Dec, plate scale]
related: [Annotation, CatalogAnnotation, StarAlignment, GaiaCatalog]
icon: map-pin
references:
  - "Lang, D. et al. — Astrometry.net: Blind astrometric calibration of arbitrary astronomical images (AJ, 2010)."
  - "astrometry (PyPI) — offline solving engine, Python bindings for the Astrometry.net solver."
  - "astroquery.astrometry_net — Astrometry.net web API client."
  - "photutils — DAOStarFinder, point-source detection."
---

## Summary

`PlateSolve` maps the image's pixels onto celestial coordinates (right ascension / declination)
by matching the field's stars against a reference catalog. The result — a **WCS** (World
Coordinate System) solution — is stored on `window.wcs`; pixels are **never modified**. Two
backends are available: `astrometry`, a pure-Python **offline** engine relying on index files
downloaded once and then cached (default), and `astrometry_net`, which queries the
Astrometry.net **web service** through `astroquery` (requires an API key and a network
connection).

## Use cases

- Obtain a **WCS solution** to subsequently draw an RA/Dec grid with `Annotation`, or overlay
  a star catalog with `CatalogAnnotation`.
- Precisely identify the **framing** of an image whose pointing coordinates are unknown or
  only approximate (mount drift, an image received without metadata).
- Measure the actual **plate scale** (arcsec/pixel) and orientation of the sensor.
- Provide the celestial reference frame needed by photometric processing or by catalog
  queries (`GaiaCatalog`, `APASSCatalog`) centered on the observed field.

## How it works

1. **Star detection** — the luminance (mean of the channels) is analyzed with
   `DAOStarFinder` (photutils) after a robust background estimate from sigma-clipped
   statistics (median, standard deviation, `sigma=3`). Detection threshold: 5σ, assumed
   stellar FWHM: 3 px. Sources are sorted by decreasing flux and truncated to `max_stars`
   to keep the solver's workload bounded (too many stars → combinatorial explosion).
2. **Offline backend (`astrometry`)** — selects the index series (`series`, e.g. Tycho-2
   `4200`, reliable and hosted on `data.astrometry.net`, or Gaia `5200`, larger and hosted
   on NERSC), downloads into `cache_dir` (default
   `~/.cache/retina/astrometry-indexes`) any missing index files for the requested
   `scales`, then runs the `Solver` on the pixel star list. A `SizeHint`
   (`scale_low`/`scale_high`) and a `PositionHint` (`ra`/`dec`/`radius`) optionally
   restrict the search space. If no match is found, an error is raised.
3. **Online backend (`astrometry_net`)** — sends the pixel star list and the image
   dimensions to the web service via `astroquery.astrometry_net.AstrometryNet`
   (API key required), with optional scale bounds and `timeout`. The returned FITS
   header is converted into an `astropy.wcs.WCS` object.
4. The WCS solution is assigned to `view.window.wcs`. This is a pure **read/analysis**
   process: no history entry is pushed, and pixel data stays untouched.

## Mathematics

**Quad geometric-hash matching.** The Astrometry.net engine (both offline and online
backends share the same principle) does not compare raw star patterns but **geometric
invariants**. For every group of 4 stars (a "quad"), the two farthest apart define the
diagonal of a normalized local frame (scale and rotation removed); the other two stars
then have coordinates $(x_1, y_1, x_2, y_2) \in [0,1]^4$ in that frame, forming a **hash
code** invariant to the image's translation, scale and rotation. That code is looked up
(via a kd-tree) among the precomputed quads of the chosen index series; each candidate is
then **verified** by testing whether a much larger set of detected stars aligns with the
catalog at the proposed position/scale (a Bayesian consistency test), which rejects false
positives even with a small star count.

**Gnomonic (TAN) projection.** Once the tangent point $(\alpha_0, \delta_0)$ and the `CD`
matrix (rotation + scale) are determined, the WCS solution relates pixel $(x, y)$ to
standard coordinates $(\xi, \eta)$ by:

$$ \begin{pmatrix}\xi\\ \eta\end{pmatrix} =
   \begin{pmatrix}CD_{11}&CD_{12}\\ CD_{21}&CD_{22}\end{pmatrix}
   \begin{pmatrix}x-x_0\\ y-y_0\end{pmatrix}, $$

and the gnomonic deprojection yields sky coordinates:

$$ \alpha = \alpha_0 + \arctan\!\left(\frac{\xi}{\cos\delta_0 - \eta\sin\delta_0}\right), \qquad
   \delta = \arcsin\!\left(\frac{\sin\delta_0 + \eta\cos\delta_0}{\sqrt{1+\xi^2+\eta^2}}\right). $$

The local **plate scale** (arcsec/pixel) is approximately $3600 \cdot
\sqrt{\lvert \det(CD)\rvert}$ (in degrees/pixel before conversion): this is the quantity
that `scale_low`/`scale_high` bound to speed up and make the search more reliable.

## Parameters

- **`backend`** — *enum*, default `astrometry`, choices `astrometry` / `astrometry_net`.
  Solving engine: offline (local index files) or the Astrometry.net web service.
- **`series`** — *enum*, default `4200`, choices `4100`, `4200`, `5000`, `5200`, `5200_heavy`,
  `6000`, `6100`. Index file series used in offline mode (`astrometry` backend).
- **`scales`** — *intlist*, default `[8, 9, 10, 11]`. Index scales (Astrometry.net scale ids)
  to download/use, matched to the image's actual field of view — `[8-11]` covers roughly
  30′–120′.
- **`cache_dir`** — *path*, default `""`. Cache directory for offline index files; empty =
  `~/.cache/retina/astrometry-indexes`.
- **`ra`** — *real*, default `0.0`, range `0`–`360`. Approximate right ascension of the field
  center, in degrees (`0` = blind search).
- **`dec`** — *real*, default `0.0`, range `-90`–`90`. Approximate declination of the center,
  in degrees.
- **`radius`** — *real*, default `0.0`, range `0`–`180`. Search radius around `ra`/`dec`, in
  degrees (`0` = no positional constraint, blind search).
- **`scale_low`** — *real*, default `0.0`, range `0`–`3600`. Expected minimum scale, in
  arcsec/pixel (`0` = no lower bound).
- **`scale_high`** — *real*, default `0.0`, range `0`–`3600`. Expected maximum scale, in
  arcsec/pixel (`0` = no upper bound).
- **`max_stars`** — *int*, default `100`, range `10`–`1000`. Maximum number of (brightest)
  stars passed to the solver.
- **`api_key`** — *str*, default `""`. Astrometry.net API key, required only by the online
  backend (`astrometry_net`).
- **`timeout`** — *int*, default `120`, range `30`–`1200`. Maximum time (seconds) allowed for
  the online solve before failing.

## Tips & pitfalls

> **Warning** — fewer than 10 detected stars make the process fail with an explicit error.
> On star-poor fields (a heavily stretched full-frame nebula, a tight crop) lower the
> upstream detection threshold or supply a less aggressively processed image.

> **Note** — the first call to the offline backend downloads any missing index files
> (network required just once); subsequent solves are **fully offline**. Series `4200`
> (Tycho-2) is reliable and quick to download; `5200`/`5200_heavy` (Gaia) are more complete
> but larger and hosted elsewhere (NERSC).

- Providing `ra`/`dec`/`radius` and `scale_low`/`scale_high` sharply restricts the search
  space: the solve is much faster and more reliable than a fully blind search.
- Choose the `scales` to match the image's actual field of view; a wrong index scale
  prevents any match even with good stars.
- Do not raise `max_stars` without reason: beyond a certain count, solve time explodes with
  no meaningful gain in reliability.
- The WCS is stored on the **window** (`window.wcs`), not on the view: running `PlateSolve`
  on a preview still requires that the view belong to a window.

## See also

- [Annotation](retina-doc://Annotation) — RA/Dec grid drawn from the WCS obtained here.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — overlays a star catalog using this WCS.
- [StarAlignment](retina-doc://StarAlignment) — star-based inter-image registration.
- [GaiaCatalog](retina-doc://GaiaCatalog) — Gaia catalog query over the resolved field.

## References

- Lang, D. et al. — *Astrometry.net: Blind astrometric calibration of arbitrary astronomical
  images* (AJ, 2010).
- astrometry (PyPI) — offline solving engine, Python bindings for the Astrometry.net solver.
- astroquery.astrometry_net — Astrometry.net web API client.
- photutils — *DAOStarFinder*, point-source detection.
