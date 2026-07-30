---
id: GaiaCatalog
category: Global
title: Gaia Catalog
brief: Queries Gaia DR3 online to list and project onto pixel coordinates the stars in the solved (WCS) field.
keywords: [Gaia, catalog, astrometry, TAP, ADQL, WCS, plate solve, reference stars]
related: [PlateSolve, APASSCatalog, CatalogAnnotation, PhotometricColorCalibration]
icon: database
references:
  - "Gaia Collaboration — Gaia Data Release 3 (DR3), 2022."
  - "ESA/Gaia archive — TAP/ADQL access to gaiadr3.gaia_source."
  - "astroquery.gaia — Python client for the Gaia TAP+ service."
---

## Summary

`GaiaCatalog` queries the **Gaia DR3** stellar survey online (via `astroquery.gaia`) for the
portion of sky covered by the active view, then **projects every star onto pixel coordinates**
using the WCS established by `PlateSolve`. The result — a list of stars with right ascension,
declination, G magnitude and `(x, y)` position — is stored in `.result`, ready to feed
annotation, photometric color calibration, or reference-star selection. It is a pure
**measurement** process: it never modifies the image pixels.

## Use cases

- **Provide a reference star list** to `PhotometricColorCalibration` or
  `SpectrophotometricColorCalibration` for physically grounded color calibration.
- **Feed `CatalogAnnotation`** to overlay named star markers and magnitudes on the final image.
- **Check plate-solve quality**: compare the number and position of cataloged stars against
  what is actually detected in the image.
- **Pick calibration stars** for differential photometry or FWHM measurement at a precise
  location in the field.

## How it works

1. **WCS prerequisite**: the view must carry an astrometric solution (`window.wcs`), obtained
   beforehand with `PlateSolve`. Without a WCS, the process raises an explicit error.
2. **Search-radius computation**: the field center is found by projecting the central pixel
   through the WCS; the cone-search radius is the angular separation between that center and
   image corner `(0, 0)`, **capped at 3°** to avoid overly costly queries on very wide fields.
3. **TAP/ADQL query**: a query `SELECT TOP max_stars ra, dec, phot_g_mean_mag FROM
   gaiadr3.gaia_source WHERE CONTAINS(POINT(...), CIRCLE(...)) AND phot_g_mean_mag < mag_limit`
   is submitted asynchronously to the Gaia service via `astroquery.gaia.Gaia.launch_job_async`.
4. **Pixel projection**: every returned `(ra, dec)` is converted to image coordinates through
   `wcs.world_to_pixel_values`, and stars falling outside the frame `[0, w) × [0, h)` are
   dropped.
5. **Result**: `.result = {"n_stars": N, "stars": [{"ra", "dec", "mag", "x", "y"}, …]}`. No
   history entry is created (`execute_on` does not modify the view).

`APASSCatalog` follows the exact same logic but queries APASS DR9 (wide-band BVgri photometry)
via Vizier instead of Gaia.

## Mathematics

**Search radius.** The field is centered on pixel $(w/2, h/2)$, projected to celestial
coordinates $(\alpha_0, \delta_0)$ by the WCS. The cone-search radius is the great-circle
angular separation between that center and the image corner, given by the haversine formula:

$$ \Delta\sigma = 2 \arcsin\!\sqrt{\sin^2\!\Big(\tfrac{\delta_1-\delta_0}{2}\Big) +
   \cos\delta_0 \cos\delta_1 \sin^2\!\Big(\tfrac{\alpha_1-\alpha_0}{2}\Big)}, \qquad
   r = \min(\Delta\sigma,\ 3°). $$

**Cone-search query.** The filter `CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', α₀, δ₀, r))
= 1` selects sources whose angular separation from the center is less than $r$, which is exactly
the inequality above applied to every row of `gaiadr3.gaia_source`, combined with the magnitude
cut `phot_g_mean_mag < mag_limit`.

**Sky-to-pixel projection.** The WCS maps each pair $(\alpha_i, \delta_i)$ to an image position
$(x_i, y_i)$ through the standard tangent (TAN) projection: standard coordinates $(\xi, \eta)$
on the plane tangent at the field's reference point,

$$ \xi = \frac{\cos\delta \,\sin(\alpha - \alpha_0)}
   {\sin\delta_0 \sin\delta + \cos\delta_0 \cos\delta \cos(\alpha-\alpha_0)}, \qquad
   \eta = \frac{\cos\delta_0 \sin\delta - \sin\delta_0 \cos\delta \cos(\alpha-\alpha_0)}
   {\sin\delta_0 \sin\delta + \cos\delta_0 \cos\delta \cos(\alpha-\alpha_0)}, $$

after which $(\xi, \eta)$ is converted to pixels through the WCS's CD/PC matrix and reference
pixel `CRPIX` (`astropy.wcs.WCS.world_to_pixel_values`, which wraps these steps).

## Parameters

- **`mag_limit`** — *real*, default `16.0`, range `0.0`–`22.0`. Limiting Gaia G magnitude: only
  stars brighter (lower magnitude) than this threshold are kept by the query.
- **`max_stars`** — *int*, default `1000`, range `1`–`100000`. Maximum number of rows returned
  by the TAP query (`TOP` clause), before filtering against the image frame.

## Tips & pitfalls

> **Warning** — the query's `TOP max_stars` clause comes with **no `ORDER BY` on magnitude**:
> the returned stars are therefore not necessarily the brightest in the field, just the first
> `max_stars` rows in the order the Gaia service returns them. To reliably get the brightest
> stars, tighten `mag_limit` rather than relying on `max_stars` alone.

> **Note** — `GaiaCatalog` requires a valid WCS on the window (`view.window.wcs`); always run
> `PlateSolve` first, otherwise the process fails with an explicit error.

- The query is **online** (network access to the Gaia service): an `execute_on` call can take
  several seconds depending on field density and service load.
- The search radius is **capped at 3°**: on a very wide field (wide-angle lens), only part of
  the field will be covered by the downloaded catalog.
- For headless testing or offline use, `set_catalog([(ra, dec, mag), …])` lets you inject a star
  list directly and bypass the network query.
- Stars outside the frame (projected outside `[0, w) × [0, h)`) are silently dropped from the
  result — only the actually imaged field is represented.

## See also

- [PlateSolve](retina-doc://PlateSolve) — computes the required WCS upstream.
- [APASSCatalog](retina-doc://APASSCatalog) — equivalent BVgri photometric catalog (Vizier).
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — annotates the image from a catalog.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — color calibration
  driven by cataloged reference stars.

## References

- Gaia Collaboration — *Gaia Data Release 3 (DR3)*, 2022.
- ESA/Gaia archive — TAP/ADQL access to `gaiadr3.gaia_source`.
- astroquery.gaia — Python client for the Gaia TAP+ service.
