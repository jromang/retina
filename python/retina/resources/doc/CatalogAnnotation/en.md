---
id: CatalogAnnotation
category: Astrometry
title: Catalog Annotation
brief: "Overlays objects from a catalog (Gaia DR3) via the WCS: markers + magnitudes."
keywords: [astrometry, WCS, Gaia, catalog, annotation, stars, magnitude]
related: [PlateSolve, Annotation, GaiaCatalog, EphemerisGenerator]
icon: list-details
references:
  - "Gaia Collaboration — Gaia Data Release 3 (DR3)."
  - "astroquery.gaia — Gaia TAP+/ADQL query interface."
  - "PixInsight — AnnotateImage script (catalog overlay)."
---

## Summary

`CatalogAnnotation` queries the **Gaia DR3** stellar catalog for the field covered by the
image, then **draws markers** (circles) and, optionally, the **magnitude** above each matched
source. Unlike `Annotation` (an RA/Dec coordinate grid), it places real point objects on the
image — useful for identifying stars, verifying an astrometric solution, or preparing an
annotated plate. This is a **destructive** process: it paints straight into the pixels (a
burn-in), not an editable overlay layer.

## Use cases

- **Verify a `PlateSolve` solution** by overlaying the expected Gaia positions on the image
  and visually checking their alignment with the actual stars.
- **Identify stars** in a field for an observation report or a publication.
- **Spot the brightest stars** in a field (sorted by ascending magnitude) before picking
  reference stars for photometry or color calibration.
- **Headless tests**: inject a synthetic catalog via `set_objects([(ra, dec, mag), …])`
  without depending on network access to Gaia.

## How it works

The process requires a **valid WCS** on the window (`window.wcs`), set beforehand by
`PlateSolve` — otherwise it raises an explicit error.

1. **Catalog retrieval**: if no catalog was supplied via `set_objects()`, an **ADQL** query is
   sent to Gaia DR3 through `astroquery.gaia.Gaia.launch_job_async`. The field center and a
   search radius (capped at 2°) are derived from the WCS; the query selects the `max_objects`
   brightest stars (`ORDER BY phot_g_mean_mag ASC`) below the `limit_mag` cutoff, within an
   ICRS `CIRCLE(...)` cone. Sorting by magnitude (rather than a plain nearest-to-center search)
   guarantees bright stars near the field edge are not missed.
2. **Sky-to-pixel projection**: each object's `(ra, dec)` coordinates are converted to image
   coordinates `(x, y)` via `wcs.world_to_pixel_values`.
3. **Rendering**: the image is converted to 8-bit RGB, then drawn on with Pillow
   (`ImageDraw.ellipse`) — a yellow circle of radius `marker_radius` per object that falls
   inside the frame, with the magnitude text attached when `labels` is on. The result is
   converted back to float32 `[0,1]` and becomes the view's new image (`view.set_image`),
   wrapped in `begin_process`/`end_process` for history and undo.

The number of objects actually annotated (inside the image frame) is available after execution
via the instance's `count` attribute.

## Mathematics

There is no signal-level pixel transform here; the operation is a **geometric projection**
followed by vector drawing. For a catalog object with celestial coordinates
$(\alpha, \delta)$ (right ascension, declination), the WCS solution $W$ (rotation/scale matrix
plus distortion) gives the pixel position:

$$ (x, y) = W^{-1}(\alpha, \delta) $$

The object is kept if $0 \le x < w$ and $0 \le y < h$ (within the image frame of width $w$ and
height $h$). The angular search radius $\rho$ of the Gaia cone is derived from the field
diagonal as seen from the center:

$$ \rho = \min\!\big(\operatorname{sep}(c,\,W(0,0)),\; 2°\big) $$

where $c$ is the image center's celestial coordinate and $\operatorname{sep}$ is the angular
separation on the sphere. The magnitude filter is a simple bound:
$m_G \le \texttt{limit\_mag}$, with ascending sort on $m_G$ to favor bright stars when
truncating to `max_objects`.

## Parameters

- **`catalog`** — *enum*, default `gaia`, choices: `gaia`. Reference catalog queried. Only
  Gaia DR3 is currently available.
- **`limit_mag`** — *real*, default `12.0`, range `-5`–`25`. Magnitude limit (Gaia G band):
  only sources brighter than this value are fetched.
- **`max_objects`** — *int*, default `300`, range `1`–`5000`. Maximum number of objects
  returned by the query (brightest first).
- **`marker_radius`** — *real*, default `6.0`, range `1.0`–`50.0`. Radius in pixels of the
  circles marking each source.
- **`labels`** — *bool*, default `True`. Show the magnitude as text next to each marker.

## Tips & pitfalls

> **Warning** — without a prior `PlateSolve` (missing WCS), the process raises a `ValueError`.
> Always solve the field before annotating.

> **Note** — the Gaia query requires network access and can be slow on wide fields or high
> `limit_mag` values (many sources). Lower `limit_mag` or `max_objects` to speed it up, or
> supply a local catalog via `set_objects()` in an offline environment.

- The rendering is **destructive**: work on a copy or a preview if you want to keep the
  original image without annotations.
- If markers are visibly offset from the real stars, this is often a sign of an imprecise
  `PlateSolve` solution or unmodeled optical distortion.
- For a coordinate grid rather than point objects, use `Annotation`.

## See also

- [PlateSolve](retina-doc://PlateSolve) — computes the WCS required upstream.
- [Annotation](retina-doc://Annotation) — RA/Dec coordinate grid overlay.
- [GaiaCatalog](retina-doc://GaiaCatalog) — direct Gaia catalog access without image annotation.
- [EphemerisGenerator](retina-doc://EphemerisGenerator) — solar system object positions via WCS.

## References

- Gaia Collaboration — *Gaia Data Release 3 (DR3)*.
- astroquery.gaia — TAP+/ADQL query interface for Gaia.
- PixInsight — *AnnotateImage* script (catalog overlay).
