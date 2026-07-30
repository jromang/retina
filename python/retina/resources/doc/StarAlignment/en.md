---
id: StarAlignment
category: ImageRegistration
title: Star Alignment
brief: Automatically registers a view onto a reference by matching star triangles (astroalign).
keywords: [registration, alignment, asterisms, astroalign, similarity, stacking]
related: [Integration, DynamicAlignment, PhaseCorrelationAlignment, FeatureAlignment]
icon: stars
references:
  - "Beroiz, M. et al. — astroalign: A Python module for astronomical image registration."
  - "PixInsight — StarAlignment tool reference."
---

## Summary

`StarAlignment` geometrically registers the active view onto a **reference image** (another
open view, given by `reference_id`, or a file on disk via `reference_path`), without using any
WCS information. The transform is estimated automatically from the stars detected in both
images, using the `astroalign` library. It is the mandatory step before any `Integration`:
without accurate registration, stacking produces doubled or blurred stars instead of a real
signal-to-noise gain.

## Use cases

- **Align a series of subs** before `Integration`, when the mount has drifted (dithering,
  imperfect tracking, meridian flip) between exposures.
- **Register frames taken on different dates** (same target, similar framing) to compare or
  combine separate sessions.
- **Re-align a channel or filter** (LRGB, narrowband) captured separately, without relying on a
  pre-existing astrometric (WCS) solution.
- Serve as the building block of a scriptable **batch preprocessing** pipeline (reference set
  once, applied to an entire batch from the console).

## How it works

1. **Reference loading** — via `_reference()`: either the pixel array of another already-open
   view (`reference_id`, resolved through `context.resolve_image_full`), or a file loaded from
   disk (`reference_path`). An error is raised if neither is provided.
2. **Reduction to luminance** — the source view and the reference are each averaged across
   channels (`data.mean(axis=2)`) to obtain a 2D grayscale image: star detection and transform
   estimation are performed on this luminance, independently of color.
3. **Star detection and asterism matching** — `astroalign.find_transform` detects sources in
   both luminance images, builds **triangles** (asterisms) for each star with its nearest
   neighbors, encodes every triangle with a geometric invariant (side-length ratios), and then
   matches source/target triangles whose invariants are close. A RANSAC-like scheme filters out
   spurious matches and fits the best **similarity transform** (rotation + scale + translation)
   in a least-squares sense over the retained correspondences.
4. **Resampling** — the resulting transform is applied independently to **each channel** of the
   source image (`astroalign.apply_transform`), which is resampled onto the reference's
   geometry. The output is clipped to `[0, 1]` and returned as `float32`.

> **Note** — the method requires **no WCS information or prior astrometry**: it works by
> recognizing stellar patterns, much as a human eye would when comparing two star fields.

## Mathematics

`astroalign` represents each triplet of stars $(P_1, P_2, P_3)$ by an **invariant** built from
the triangle's side lengths, sorted in canonical order (longest side as reference):

$$ \operatorname{inv}(P_1,P_2,P_3) = \left(\frac{\ell_2}{\ell_1},\ \frac{\ell_3}{\ell_1}\right),
\qquad \ell_1 \ge \ell_2 \ge \ell_3, $$

where $\ell_1,\ell_2,\ell_3$ are the three side lengths. This invariant is **independent of
rotation, translation and scale**: two triangles corresponding to the same stellar configuration,
seen in two different images, have nearly identical invariants even if the field has rotated or
zoomed between the two exposures. Source and target triangles are matched by nearest-neighbor
search in this invariant space (tolerance $r$), and a robust RANSAC-like algorithm then selects
the largest set of mutually consistent matches (reprojection error under a `PIXEL_TOL` threshold).

The estimated transform is a 2D **similarity**, mapping a source point $\mathbf{x} = (x, y)$ to
$\mathbf{x}' = (x', y')$ in the reference frame:

$$ \begin{pmatrix} x' \\ y' \end{pmatrix}
   = s \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
     \begin{pmatrix} x \\ y \end{pmatrix} + \begin{pmatrix} t_x \\ t_y \end{pmatrix}, $$

with a scale factor $s$, a rotation angle $\theta$, and a translation $(t_x, t_y)$ shared across
the whole image (4 degrees of freedom). The parameters are fit in a least-squares sense over all
star correspondences kept as inliers by RANSAC. This transform, once inverted, is applied by
interpolation to each channel of the source image to produce the output on the reference's grid.

> **Warning** — a **similarity** models neither optical distortion nor projection (no shear, no
> perspective): for very wide fields or optics with strong edge-of-field distortion, a slight
> residual misalignment may remain at the periphery. `DynamicAlignment` (`affine`/`projective`
> transform on hand-picked points) handles those cases.

## Parameters

- **`reference_id`** — *str*, default `""`. Identifier of an already-open view to use as the
  registration reference, resolved through the execution context
  (`context.resolve_image_full`).
- **`reference_path`** — *path*, default `""`. Path of an image file to load as the reference,
  used instead of an open view. Takes priority over `reference_id` when set.

> **Note** — one of the two parameters must be provided; if both `reference_id` and
> `reference_path` are empty, the process raises an explicit `ValueError`.

## Tips & pitfalls

> **Warning** — `astroalign` fails (`MaxIterError` or `ValueError`) if fewer than 3 sharp stars
> are detected in either image (too sparse a field, too noisy an image, or nebulosity with no
> point-like stars). In that case, prefer `PhaseCorrelationAlignment` (no source detection) or
> `DynamicAlignment` (hand-clicked points).

- Pick the **sharpest, best-exposed** sub of the set as the reference (best FWHM, minimal star
  trailing): the quality of the stars detected in the reference drives the accuracy of the whole
  match.
- Detection and estimation run on **luminance**: a heavily degraded sky background or a strong
  gradient can produce spurious detections; a prior `BackgroundExtraction` (on a copy) sometimes
  improves robustness.
- Registration changes the output geometry (reference dimensions): parts of the source image
  falling outside the reference frame are lost, and non-overlapping areas are filled with zeros.

## See also

- [Integration](retina-doc://Integration) — stacking of the subs once aligned.
- [DynamicAlignment](retina-doc://DynamicAlignment) — manual registration via control points
  (similarity/affine/projective), useful when automatic detection fails.
- [PhaseCorrelationAlignment](retina-doc://PhaseCorrelationAlignment) — registration by phase
  correlation, without star detection.
- [FeatureAlignment](retina-doc://FeatureAlignment) — registration via interest points (outside
  purely stellar fields).

## References

- Beroiz, M. et al. — *astroalign: A Python module for astronomical image registration*.
- PixInsight — *StarAlignment* tool reference.
