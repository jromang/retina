---
id: Annotation
category: Astrometry
title: Annotation
brief: Draws a celestial coordinate grid (RA/Dec) on the image from its WCS solution.
keywords: [astrometry, WCS, grid, RA/Dec, celestial coordinates, plate-solving]
related: [PlateSolve, CatalogAnnotation, GaiaCatalog]
icon: tag
references:
  - "PixInsight — AnnotateImage script reference."
  - "astropy.wcs — World Coordinate System transformations."
  - "FITS WCS Paper II (Calabretta & Greisen, 2002)."
---

## Summary

`Annotation` overlays an **equatorial coordinate grid** (right ascension and declination) on the
image, computed from the window's astrometric solution (WCS). It is the equivalent of the "grid"
pane of PixInsight's `AnnotateImage` script: once the field has been solved by `PlateSolve`, this
grid lets you visually verify the orientation, scale and validity of the astrometric registration,
or simply dress up an image for publication.

## Use cases

- **Check an astrometric solution**: a consistent grid (regular, untwisted lines) confirms that the
  WCS computed by `PlateSolve` is correct.
- **Read off the field orientation** (north/east) before a mosaic composition or a comparison
  between sessions.
- **Illustrate a published image** with coordinate markers, sky-atlas style.
- **Diagnose a distortion**: a visibly curved or irregular grid betrays a poorly solved WCS or a
  field with strong, unmodelled optical distortion.

## How it works

The process requires a WCS already present on the window (`window.wcs`), set by `PlateSolve` —
without an astrometric solution it fails explicitly rather than improvising an arbitrary grid.

1. For **every pixel** of the image, image coordinates `(x, y)` are converted to celestial
   coordinates `(RA, Dec)` via `wcs.pixel_to_world`, producing two full-size maps `ra(x,y)` and
   `dec(x,y)`.
2. For each of the two maps, the proximity to the nearest multiple of the **grid spacing**
   `grid_spacing` is tested: pixels whose RA (or Dec) falls within `line_width` of a multiple form
   the grid lines.
3. The image is converted to color if necessary (mono images are duplicated across 3 channels),
   then the marked pixels are painted **pure green** `(0, 1, 0)`.
4. The operation is **destructive**: it rewrites pixel values and is recorded in the view history
   (`begin_process`/`end_process`), unlike a display-only overlay grid.

## Mathematics

Let $W$ be the window's pixel-to-sky WCS transform. For each pixel $(x, y)$:

$$ (\alpha, \delta) = W(x, y) $$

where $\alpha$ is right ascension and $\delta$ is declination, in degrees. For a coordinate
$c \in \{\alpha, \delta\}$ and a spacing $g$ = `grid_spacing`, define the reduced offset to the
nearest multiple of $g$:

$$ f(c) = \left| \frac{c}{g} - \operatorname{round}\!\left(\frac{c}{g}\right) \right| $$

$f(c)$ is $0$ exactly on meridians/parallels that are multiples of $g$, and grows linearly to
$0.5$ halfway between two lines. A pixel belongs to the grid if either coordinate is close enough
to a line, with $\ell$ = `line_width`:

$$ \text{grid}(x, y) = \big[\, f(\alpha(x,y)) < \ell \,\big] \;\lor\; \big[\, f(\delta(x,y)) < \ell \,\big] $$

This test produces a periodic pattern of period $g$ in each celestial direction — equivalent to a
thresholded sawtooth function. The apparent thickness of the lines on the image therefore depends
both on `line_width` and on the local scale (arcsec/pixel), which varies with declination
(meridians converging toward the poles) and with the projection used by the WCS.

## Parameters

- **`grid_spacing`** — *real*, default `0.5`, range `0.001`–`90.0`. Grid spacing in degrees,
  applied identically in RA and Dec. Decrease for a narrow field (cluster, galaxy), increase for a
  wide field (Milky Way, mosaic).
- **`line_width`** — *real*, default `0.02`, range `0.001`–`0.2`. Line thickness, expressed as a
  **fraction of the grid spacing** (not pixels). Too large a value merges neighboring lines or
  floods the image.

## Tips & pitfalls

> **Warning** — `Annotation` **modifies the pixels** (the grid is baked in, in green). Work on a
> copy of the window, or apply this process at the end of the workflow, after the final stretch.

> **Note** — without a valid WCS on the window, the process raises an explicit error. Run
> `PlateSolve` first; an imprecise solution shows up as a visibly shifted or warped grid.

- Near the celestial poles, the convergence of RA meridians produces very tightly packed RA lines:
  lower `grid_spacing` with caution on such fields.
- To label named objects (stars, catalog entries) instead of a plain coordinate grid, use
  `CatalogAnnotation`.

## See also

- [PlateSolve](retina-doc://PlateSolve) — computes the required prior astrometric solution (WCS).
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — overlays catalog objects (Gaia) instead of a grid.
- [GaiaCatalog](retina-doc://GaiaCatalog) — direct Gaia catalog query over the field.

## References

- PixInsight — *AnnotateImage* script reference.
- astropy.wcs — *World Coordinate System* transformations.
- FITS WCS Paper II (Calabretta & Greisen, 2002).
