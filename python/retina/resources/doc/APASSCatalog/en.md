---
id: APASSCatalog
category: Global
title: APASS Catalog
brief: Queries the APASS DR9 photometric catalog (Vizier II/336) and projects field stars into pixel coordinates via the WCS.
keywords: [APASS, catalog, photometry, Vizier, WCS, color calibration, V magnitude]
related: [PlateSolve, GaiaCatalog, PhotometricColorCalibration, CatalogAnnotation]
icon: database
references:
  - "Henden, A. A. et al. — The AAVSO Photometric All-Sky Survey (APASS), DR9."
  - "Vizier catalogue II/336 — APASS DR9."
  - "astroquery.vizier — Vizier query interface."
---

## Summary

`APASSCatalog` performs an online query against the **APASS DR9** catalog (*AAVSO Photometric
All-Sky Survey*, Vizier table `II/336`) to retrieve the stars covered by the active view's
field, then projects their celestial coordinates into pixel positions using the window's WCS.
It is a **read-only measurement** process: it never touches pixel data or opens a new window —
the result is stored in `.result` and feeds other tools (annotation, photometric calibration,
reference-star selection).

APASS is a **multi-band photometric catalog** (Johnson B, V and Sloan g′, r′, i′), which makes
it particularly useful for **color calibration** of wide-band instruments, unlike Gaia which
only provides a single broad photometric magnitude (`phot_g_mean_mag`).

## Use cases

- **Photometric color calibration**: supply reference B/V/g′/r′/i′ magnitudes to fit the color
  coefficients of a wide-band camera.
- **Reference-star selection** for differential photometry or instrument calibration.
- **Field annotation**: overlay catalog star positions and magnitudes on the image (via
  `CatalogAnnotation`).
- **Plate-solve cross-check**: compare expected APASS star positions against positions measured
  in the image.

## How it works

The process is built on the shared base class `_CatalogQuery`, also used by `GaiaCatalog`:

1. **WCS prerequisite** — the view must carry an astrometric solution (`view.window.wcs`),
   typically produced by `PlateSolve`. Without a WCS, execution fails explicitly.
2. **Network query** — the field center is computed by projecting the WCS at the image center
   (`w/2, h/2`), and a search radius is derived from the angular separation between that center
   and the `(0, 0)` corner, capped at 3°. An `astroquery.vizier.Vizier` request queries the
   `II/336` table as a cone search around that center, filtered on `Vmag < mag_limit` and
   limited to `max_stars` rows.
3. **Pixel projection** — each returned star `(ra, dec, mag)` is converted to image coordinates
   via `wcs.world_to_pixel_values`, and only stars whose projected position falls **within the
   image bounds** are kept.
4. **Result** — a dictionary `{"n_stars": int, "stars": [...]}` is stored in `.result`, each
   entry carrying `ra`, `dec`, `mag` (V magnitude) and pixel coordinates `x`, `y`.

For headless testing or offline use, `set_catalog([(ra, dec, mag), ...])` lets you inject an
explicit list of objects and bypass the network query entirely.

## Mathematics

The process implements no image-processing algorithm; its only mathematical component is the
**WCS projection geometry** and the search-radius computation.

The cone-search radius is the angular separation between the field center $c$ (the pixel
$(w/2, h/2)$ projected onto the sky) and the corner $(0,0)$ likewise projected, capped at $3°$:

$$ r = \min\big(\operatorname{sep}(c,\, \text{corner}_{0,0}),\ 3°\big). $$

Each catalog star $(\alpha_i, \delta_i)$ (right ascension, declination) is re-projected into
pixel coordinates through the inverse WCS transform $W^{-1}$:

$$ (x_i, y_i) = W^{-1}(\alpha_i, \delta_i). $$

A star is kept if its projection falls inside the image frame $(H, W)$:

$$ 0 \le x_i < W \quad\text{and}\quad 0 \le y_i < H. $$

Magnitude filtering is a simple inequality applied server-side by Vizier:
$V_i < \texttt{mag\_limit}$, which bounds the depth of the catalog queried rather than the list
returned after projection.

## Parameters

- **`mag_limit`** — *real*, default `16.0`, range `0`–`22`. V-band magnitude limit: only APASS
  stars brighter than this threshold are kept by the Vizier query.
- **`max_stars`** — *int*, default `1000`, range `1`–`100000`. Maximum number of stars returned
  by the query (Vizier `row_limit`), before projection and image-frame filtering.

## Tips & pitfalls

> **Warning** — without a valid WCS on the window (`view.window.wcs`), the call raises an
> explicit `ValueError` prompting you to run `PlateSolve` first.

> **Note** — the search radius is capped at 3°: on a very wide field (short focal length, wide
> lens), the query may cover only part of the frame. Check `n_stars` in `.result` if coverage
> looks incomplete.

- APASS provides **B, V, g′, r′, i′** in the `II/336` Vizier table, but only the `Vmag` column
  is fetched here: for a full multi-band calibration, adapt the query or use `set_catalog(...)`
  with your own data.
- The query depends on network access to Vizier; for offline environments or tests, inject an
  explicit catalog via `set_catalog([(ra, dec, mag), ...])`.
- The result creates **no history entry** and no window: it is a pure measurement, consistent
  with the read-only nature of catalog processes.

## See also

- [PlateSolve](retina-doc://PlateSolve) — computes the WCS required before any catalog query.
- [GaiaCatalog](retina-doc://GaiaCatalog) — Gaia DR3 equivalent, single broad photometric band.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — color calibration
  driven by catalog references.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — overlays cataloged stars on the image.

## References

- Henden, A. A. et al. — *The AAVSO Photometric All-Sky Survey (APASS)*, DR9.
- Vizier catalogue *II/336* — APASS DR9.
- astroquery.vizier — Vizier query interface.
