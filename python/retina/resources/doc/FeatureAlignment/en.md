---
id: FeatureAlignment
category: ImageRegistration
title: Feature-based Alignment (ORB)
brief: Registers a view onto a reference by matching ORB feature descriptors and estimating a RANSAC homography — no star catalog needed.
keywords: [registration, ORB, homography, RANSAC, OpenCV, mosaic, non-stellar]
related: [StarAlignment, PhaseCorrelationAlignment, DynamicAlignment, MosaicReproject]
icon: target
references:
  - "Rublee, E. et al. — ORB: An efficient alternative to SIFT or SURF (ICCV 2011)."
  - "OpenCV — ORB, BFMatcher, findHomography (RANSAC), warpPerspective."
  - "Fischler, M. A. & Bolles, R. C. — Random Sample Consensus (RANSAC), 1981."
---

## Summary

`FeatureAlignment` registers the active view onto a reference image by detecting **ORB feature
points** (Oriented FAST and Rotated BRIEF), matching their binary descriptors, and estimating a
**robust homography** (RANSAC) that maps the source geometry onto the reference. Unlike
`StarAlignment` (astroalign, based on star triangles), it assumes **no catalog of point-like
stars**: it works on any contrasted texture — landscapes, terrestrial panoramas, planetary
mosaics, or any field where star-based registration fails for lack of usable landmarks.

## Use cases

- **Non-stellar fields**: nightscapes, foreground elements, extended planetary targets, where
  `StarAlignment` has no star pattern to match against.
- **Terrestrial or near-field mosaics** whose overlap contains textured detail (terrain,
  structures) rather than point-like stars.
- **Fallback** when `StarAlignment` fails (star-poor field, strong distortion, rotation/zoom
  between exposures): the ORB homography tolerates rotation, scale, and perspective.
- Registering views from **different instruments or optics** that introduce a projective
  deformation between source and reference.

## How it works

Processing runs in four stages, on luminance (channel mean) converted to 8-bit grayscale:

1. **ORB detection**: the ORB detector extracts up to `max_features` interest points in both the
   source view and the reference, each paired with a rotation-invariant binary descriptor
   (256 bits).
2. **Matching**: a `BFMatcher` using Hamming distance, with `crossCheck` enabled (a source point
   is kept only if its best reference match also points back to it), matches descriptors between
   the two images; pairs are sorted by increasing distance.
3. **Homography estimation**: `cv2.findHomography` with RANSAC (5 px reprojection threshold)
   searches for the $3\times3$ projective transform explaining the largest consistent subset of
   matches, discarding false positives (outliers).
4. **Resampling**: `cv2.warpPerspective` applies the homography to each channel independently
   (bilinear interpolation), output at the reference's geometry.

The process fails explicitly with an error if fewer than 4 points are detected in either image,
if fewer than 4 matches survive, or if the homography cannot be estimated — 4 non-collinear
correspondences are the theoretical minimum needed to fix a projective transform with 8 degrees
of freedom.

## Mathematics

A **homography** is a $3\times3$ projective transform, defined up to scale, that maps an image
point $(x, y)$ in the source onto $(x', y')$ in the reference through homogeneous coordinates:

$$
\begin{pmatrix} x' \\ y' \\ 1 \end{pmatrix} \sim
H \begin{pmatrix} x \\ y \\ 1 \end{pmatrix}, \qquad
H = \begin{pmatrix} h_{11} & h_{12} & h_{13} \\ h_{21} & h_{22} & h_{23} \\
h_{31} & h_{32} & 1 \end{pmatrix}
$$

or, after dividing by the homogeneous coordinate:

$$
x' = \frac{h_{11}x + h_{12}y + h_{13}}{h_{31}x + h_{32}y + 1}, \qquad
y' = \frac{h_{21}x + h_{22}y + h_{23}}{h_{31}x + h_{32}y + 1}.
$$

$H$ has 8 degrees of freedom (the global scale factor is fixed), so **4 non-collinear point
correspondences** theoretically suffice to determine it. In practice, ORB matches contain false
positives: **RANSAC** repeatedly draws minimal samples of 4 pairs, computes the candidate
homography, and counts matches whose reprojection error stays under a threshold $\tau$
(here 5 pixels):

$$
\text{inliers}(H) = \Big\{\, i \;:\; \big\lVert \pi(H\, \mathbf{p}_i) - \mathbf{p}_i' \big\rVert_2
\le \tau \,\Big\}
$$

where $\pi(\cdot)$ is the homogeneous-to-Cartesian projection. The retained homography is the one
maximizing $|\text{inliers}(H)|$, optionally refined by least squares over those inliers alone.
Final resampling applies $H^{-1}$ pixel by pixel (per channel) with bilinear interpolation to
populate the output grid.

## Parameters

- **`reference_id`** — *str*, default `""`. Identifier of the open reference view to align the
  active view onto. Ignored if `reference_path` is set.
- **`reference_path`** — *path*, default `""`. Path to a reference file to load directly (takes
  precedence over `reference_id`). Handy for aligning onto a file outside the session.
- **`max_features`** — *int*, default `2000`, range `50`–`20000`. Maximum number of ORB points
  extracted per image. More points raises the odds of finding enough reliable matches on
  texture-poor fields, at the cost of longer computation.

## Tips & pitfalls

> **Warning** — the RANSAC threshold (5 px, fixed) and `max_features` are the only exposed
> knobs: on a very noisy or low-texture image, raise `max_features` before concluding the
> alignment has failed.

> **Note** — the homography is a **general projective transform** (it can model perspective),
> unlike the implicit rigid similarity of `StarAlignment`. On a purely stellar field with no
> perspective distortion, prefer `StarAlignment`, which is more robust and specifically tuned to
> star triangles.

- Normalize to consistent grayscale first: the process averages channels internally, so a very
  colored sky background or a saturated channel can degrade the contrast ORB relies on.
- If the "not enough matchable ORB points" error occurs on a starfield, try `StarAlignment`
  (star triangles) or `PhaseCorrelationAlignment` (pure translation) instead.
- For manually entered correspondences (when ORB fails outright), see `DynamicAlignment`.

## See also

- [StarAlignment](retina-doc://StarAlignment) — automatic registration via star triangles (astroalign).
- [PhaseCorrelationAlignment](retina-doc://PhaseCorrelationAlignment) — pure sub-pixel translation registration, star-free.
- [DynamicAlignment](retina-doc://DynamicAlignment) — registration from manually entered control points.
- [MosaicReproject](retina-doc://MosaicReproject) — mosaic assembly via WCS reprojection.

## References

- Rublee, E. et al. — *ORB: An efficient alternative to SIFT or SURF* (ICCV 2011).
- OpenCV — *ORB*, *BFMatcher*, *findHomography* (RANSAC), *warpPerspective*.
- Fischler, M. A. & Bolles, R. C. — *Random Sample Consensus* (RANSAC), 1981.
