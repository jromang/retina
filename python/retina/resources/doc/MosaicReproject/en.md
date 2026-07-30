---
id: MosaicReproject
category: ImageIntegration
title: WCS Mosaic Reprojection
brief: Reprojects and co-adds several plate-solved FITS frames onto a common celestial grid to build an astrometric mosaic.
keywords: [mosaic, reprojection, WCS, astrometry, plate-solve, wide field, reproject]
related: [PlateSolve, GradientMergeMosaic, Integration, Annotation]
icon: grid-4x4
references:
  - "reproject (astropy-affiliated) — mosaicking.reproject_and_coadd / find_optimal_celestial_wcs."
  - "astropy.wcs — World Coordinate System for FITS."
  - "PixInsight — astrometric (WCS-based) mosaicking practice."
---

## Summary

`MosaicReproject` assembles several **plate-solved** images (each carrying a valid WCS in its
FITS header) into a single **astrometric mosaic**. Unlike gradient-blend merges that align
images against each other by content correlation, here the **sky itself is the reference
frame**: each frame is reprojected onto an automatically computed common celestial grid, and
overlaps are then co-added. This is a **global** process: it does not act on the active view
but reads a list of files and produces a **new window** (`new_image_id`).

## Use cases

- **Assemble a wide field** (extended nebula, Milky Way region) from several tiles acquired
  separately and individually plate-solved.
- **Combine sessions with different scales or orientations** (different focal lengths/sensors):
  reprojecting onto a common WCS natively handles rotation and scale changes.
- **Merge acquisitions taken on different nights** without relying on star-based registration —
  only the WCS astrometry matters.

## How it works

1. Each file in `frames` is opened with `astropy.io.fits`; the first HDU carrying data is kept,
   along with its **celestial** WCS (`WCS(header).celestial`, RA/Dec, ignoring any non-spatial
   axes).
2. `reproject.mosaicking.find_optimal_celestial_wcs` computes, from all the input WCS objects
   and footprints, an **optimal output WCS** and grid shape (`shape_out`) covering the union of
   all fields, with a consistent pixel scale.
3. For each channel (0 for mono, up to 3 for RGB — mono frames are repeated on the last
   available channel if the channel counts differ), `reproject.mosaicking.reproject_and_coadd`
   reprojects every frame onto the common grid via **interpolation** (`reproject_interp`) and
   **co-adds** the overlaps according to `combine` (`mean` or `sum`).
4. Areas covered by no frame produce `NaN`, replaced with 0 (`np.nan_to_num`). The result is
   stacked into `(H, W, C)`, clipped to `[0, 1]`, and published as a new window via
   `app.new_window`.

> **Note** — the celestial WCS is extracted only from **channel 0** of each frame; for a color
> mosaic this implicitly assumes all channels of a given frame share the same astrometry (the
> normal case for an internally aligned RGB image).

## Mathematics

Let $I_i$ be the image of frame $i$ with WCS $W_i$ (pixel → celestial RA/Dec transform), and
$W_\text{out}$ the output WCS on the common grid. For each output pixel $(x, y)$, interpolation
reprojection computes the corresponding celestial coordinate $W_\text{out}(x,y)$, converts it
to pixel coordinates of frame $i$ via $W_i^{-1}$, and interpolates $I_i$ at that position:

$$ \hat I_i(x,y) = I_i\big(W_i^{-1}(W_\text{out}(x,y))\big), $$

together with a **coverage footprint** $F_i(x,y) \in \{0,1\}$ equal to 1 if $(x,y)$ falls
inside frame $i$'s field, 0 otherwise (out-of-field regions are not extrapolated).

Over overlaps, co-addition combines the frames covering each pixel,
$K(x,y) = \{\, i : F_i(x,y) = 1 \,\}$, according to `combine`:

$$
M(x,y) =
\begin{cases}
\dfrac{1}{|K(x,y)|} \displaystyle\sum_{i \in K(x,y)} \hat I_i(x,y) & \text{if } \texttt{combine = mean} \\[10pt]
\displaystyle\sum_{i \in K(x,y)} \hat I_i(x,y) & \text{if } \texttt{combine = sum}
\end{cases}
$$

If $K(x,y) = \varnothing$ (no frame covers that pixel), the value is undefined ($\mathrm{NaN}$)
and replaced with 0 in the output. The `mean` mode preserves the original photometric scale
(useful for a mosaic that is directly displayable); the `sum` mode accumulates signal from
overlaps (useful if the mosaic is later re-integrated in a flux-calibration pipeline).

## Parameters

- **`frames`** — *pathlist*, default `[]`. List of plate-solved FITS files to assemble. Each
  file must carry a valid WCS in its header (see `PlateSolve`).
- **`combine`** — *enum*, default `mean`, choices: `mean`, `sum`. Combination mode for pixels
  covered by several frames: average (photometry preserved) or sum (accumulation).
- **`new_image_id`** — *str*, default `mosaic`. Identifier of the resulting window.

## Tips & pitfalls

> **Warning** — every frame must be **plate-solved beforehand** (`PlateSolve`): without a
> usable WCS in the header, reprojection fails or produces an inconsistent WCS. An approximate
> WCS (wrong scale or rotation) shows up as visibly offset seams between tiles.

- The output grid is computed automatically to cover **all** frames; a frame far off from the
  others can blow up the final image size.
- Overlap regions gain SNR (especially in `mean` mode), while each tile's edges (covered by a
  single frame only) stay at the original noise level — seams can remain visible if exposure or
  sky background differs strongly between sessions; consider `BackgroundExtraction`/
  `GradientCorrection` upstream on each tile.
- For fields without reliable astrometric solving (no usable WCS), prefer content-based
  registration with `GradientMergeMosaic`.

## See also

- [PlateSolve](retina-doc://PlateSolve) — computes the WCS required before mosaicking.
- [GradientMergeMosaic](retina-doc://GradientMergeMosaic) — gradient-blend mosaicking, no WCS needed.
- [Integration](retina-doc://Integration) — multi-frame stacking with robust rejection (identical field).
- [Annotation](retina-doc://Annotation) — overlay an RA/Dec grid on the resulting mosaic.

## References

- reproject (astropy-affiliated) — *mosaicking.reproject_and_coadd* / *find_optimal_celestial_wcs*.
- astropy.wcs — World Coordinate System for FITS.
- PixInsight — astrometric (WCS-based) mosaicking practice.
