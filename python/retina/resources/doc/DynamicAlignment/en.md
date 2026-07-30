---
id: DynamicAlignment
category: ImageRegistration
title: Dynamic Alignment
brief: Manual registration from explicit source/target control points, with geometric transform estimation and resampling.
keywords: [registration, control points, homography, affine, projective, mosaic, resampling]
related: [StarAlignment, PhaseCorrelationAlignment, FeatureAlignment, MosaicReproject]
icon: target
references:
  - "PixInsight — DynamicAlignment tool reference."
  - "scikit-image — skimage.transform.estimate_transform / warp."
  - "Hartley, R. & Zisserman, A. — Multiple View Geometry in Computer Vision (projective transforms, DLT)."
---

## Summary

`DynamicAlignment` is the scriptable core of **manual** registration: instead of detecting
stars automatically, it takes explicit **source → target** control-point pairs (typically
picked with the mouse by the dynamic GUI tool of the same name), derives the geometric
transform that maps them onto one another, then resamples the whole source image according to
that transform. It is the fallback when `StarAlignment` fails — star-poor fields, mosaics with
low overlap, non-stellar images.

## Use cases

- **Registering star-poor fields** (very extended nebulae, comets close to the foreground,
  planetary images) where automatic detection lacks reliable landmarks.
- **Mosaic assembly** by manually clicking a few common landmarks between panels that overlap
  only slightly.
- **Fine correction after an imperfect automatic registration**: a handful of extra points
  placed on poorly aligned regions.
- **Aligning non-astronomical images** within the same pipeline (ground calibration,
  instrument framing) where no star catalog makes sense.

## How it works

1. The `source` and `target` points are supplied as flat lists `[x0, y0, x1, y1, …]` in pixel
   coordinates and reshaped into `(N, 2)` arrays. At least two pairs are required, and the
   number of source and target points must match.
2. `skimage.transform.estimate_transform(mode, src, dst)` fits, in a least-squares sense (or
   via DLT for the projective mode), the transform that maps the `source` points onto the
   `target` points.
3. If `reference` names an existing view, the output geometry (width/height) is taken from that
   view; otherwise the source image's geometry is kept.
4. Each channel is resampled independently by `skimage.transform.warp`, using the **inverse
   transform** (target → source), bilinear interpolation (`order=1`), and zero-fill
   (`mode="constant", cval=0.0`) outside the source frame.
5. The result is clipped to `[0, 1]` and cast back to `float32`.

> **Note** — the transform is applied to the **entire image**, not just the region covered by
> the points: the points only serve to estimate the geometric model's parameters.

## Mathematics

Given source points $\{(x_i, y_i)\}_{i=1}^N$ and target points $\{(x_i', y_i')\}_{i=1}^N$,
`mode` selects a homogeneous transform model $T$ such that $T(x_i, y_i) \approx (x_i', y_i')$:

- **`similarity`** (4 degrees of freedom — rotation $\theta$, uniform scale $s$, translation
  $(t_x, t_y)$), $N \ge 2$:
  $$
  \begin{pmatrix} x' \\ y' \end{pmatrix} =
  s \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
  \begin{pmatrix} x \\ y \end{pmatrix} + \begin{pmatrix} t_x \\ t_y \end{pmatrix}
  $$
- **`affine`** (6 degrees of freedom), $N \ge 3$:
  $$
  \begin{pmatrix} x' \\ y' \\ 1 \end{pmatrix} =
  \begin{pmatrix} a_0 & a_1 & a_2 \\ b_0 & b_1 & b_2 \\ 0 & 0 & 1 \end{pmatrix}
  \begin{pmatrix} x \\ y \\ 1 \end{pmatrix}
  $$
- **`projective`** (8 degrees of freedom, homography), $N \ge 4$:
  $$
  \begin{pmatrix} x' \\ y' \\ 1 \end{pmatrix} \sim
  \begin{pmatrix} h_0 & h_1 & h_2 \\ h_3 & h_4 & h_5 \\ h_6 & h_7 & 1 \end{pmatrix}
  \begin{pmatrix} x \\ y \\ 1 \end{pmatrix}
  $$
  (homogeneous coordinates, divide by the third component after multiplication).

Parameters are estimated by linear least squares (`similarity`, `affine`) or by the DLT
(*Direct Linear Transform*, `projective`) method. Once $T$ is known, resampling uses $T^{-1}$:
for each output pixel $(x', y')$, evaluate $(x, y) = T^{-1}(x', y')$ in the source image and
interpolate bilinearly:

$$ I_\text{out}(x', y') = \operatorname{bilerp}\big(I_\text{src},\ T^{-1}(x', y')\big). $$

With exactly the minimum required $N$, the fit is **exact** (zero residual at the points);
beyond that, it is a **least-squares** fit that smooths out pointing inaccuracies.

## Parameters

- **`source`** — *floatlist*, default `[]`. Source points in pixels, flat list
  `[x0, y0, x1, y1, …]`, in the coordinate system of the processed image.
- **`target`** — *floatlist*, default `[]`. Corresponding target points, same format and same
  count as `source` (matched by index).
- **`mode`** — *enum*, default `affine`, choices `similarity` / `affine` / `projective`.
  Geometric transform model to estimate from the correspondences.
- **`reference`** — *str*, default `""`. Id of a reference view that fixes the output geometry
  (width/height); if empty, the source image's geometry is kept.

## Tips & pitfalls

> **Warning** — the number of points must match the chosen model: at least 2 for `similarity`,
> 3 for `affine`, 4 for `projective`. Below that, `estimate_transform` produces an ill-posed
> transform or raises an error.

> **Warning** — the `source` and `target` lists must have exactly the same number of points;
> a mismatch raises an explicit `ValueError` before any computation.

- Spread the points across the whole image rather than clustering them in one corner: this
  stabilizes the estimation and limits extrapolation error far from the landmarks.
- For purely automatic star-based registration, prefer `StarAlignment`; reserve
  `DynamicAlignment` for cases where the automatic path fails or point-by-point control is needed.
- The `projective` mode corrects perspective (useful in wide-field mosaics) but amplifies
  estimation noise if points are few or poorly distributed — prefer `affine` when the geometry
  allows it.

## See also

- [StarAlignment](retina-doc://StarAlignment) — automatic registration via star detection.
- [PhaseCorrelationAlignment](retina-doc://PhaseCorrelationAlignment) — sub-pixel, star-free
  registration by phase correlation.
- [FeatureAlignment](retina-doc://FeatureAlignment) — robust registration via ORB descriptors
  and RANSAC, no catalog required.
- [MosaicReproject](retina-doc://MosaicReproject) — mosaic assembly via WCS reprojection.

## References

- PixInsight — *DynamicAlignment* tool reference.
- scikit-image — *skimage.transform.estimate_transform / warp*.
- Hartley, R. & Zisserman, A. — *Multiple View Geometry in Computer Vision* (projective
  transforms, DLT).
