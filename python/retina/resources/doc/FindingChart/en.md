---
id: FindingChart
category: Astrometry
title: FindingChart
brief: Builds a synthetic finding chart around the field of a plate-solved window.
keywords: [finding chart, WCS, field, catalog, Gaia, astrometry]
related: [PlateSolve, Annotation, CatalogAnnotation]
icon: map-pin
---

## Summary

`FindingChart` renders a **synthetic sky chart** centered on the field of a plate-solved
window: RA/Dec grid, the **footprint** of the source field (its corners projected on the
chart), catalog stars drawn as disks scaled by magnitude, a center marker and cardinal
points (north up, east left). It is a **global** process: the chart opens as a new window
— itself plate-solved, so the celestial readout works immediately.

## Use cases

- **Locate a target** in its wider surroundings after a plate solve.
- **Document a session**: export the chart next to the master.
- **Check a mosaic plan**: does the neighboring field overlap as intended?

## How it works

A synthetic TAN WCS is built at the field center, covering `field_factor` × the source
field diagonal over `size` pixels. The grid reuses the `Annotation` tracer on this WCS;
stars come from Gaia DR3 (brightest first, ADQL cone) or from `set_objects()` in
headless/tests; the footprint is the projection of the source image corners.

## Parameters

- **Source window** — window to chart (empty = active window).
- **Chart size (px)** / **Field factor** — chart geometry.
- **Grid spacing** — degrees, `0` picks a round value from the field of view.
- **Catalog** / **Limiting magnitude** / **Max objects** — star content (`none` = grid
  and footprint only, fully offline).
- **New image id** — identifier of the produced window.

## Tips

- `catalog: none` needs no network at all — grid + footprint are pure WCS math.
- The chart window has its own WCS: `CatalogAnnotation` can annotate it too.

## See also

PlateSolve, Annotation, CatalogAnnotation
