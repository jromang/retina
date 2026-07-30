---
id: Rotation
category: Geometry
title: Rotation
brief: Rotates the image by an arbitrary angle in degrees, growing the canvas so nothing is cut off.
keywords: [rotation, geometry, angle, interpolation, crop, canvas]
related: [FastRotation, Crop, Resample, PixelInterpolation]
icon: rotate
references:
  - "PixInsight — Rotation tool reference."
  - "scipy.ndimage.rotate — interpolated array rotation documentation."
---

## Summary

`Rotation` rotates the image by an **arbitrary angle** (in degrees, positive = counterclockwise)
around its center. Unlike a plain crop, the output canvas is **grown** to hold the whole rotated
image: none of the original content is lost, and the empty corners are filled with black. This
is Retina's "fine" rotation tool, as opposed to `FastRotation`, which only handles multiples of
90° with no interpolation.

## Use cases

- **Straighten an image** slightly tilted because of a polar-alignment error or a mount not
  perfectly aligned with the desired frame.
- **Align to North-up** after a plate-solve, by rotating by a known position angle.
- **Assemble a manual mosaic** where the panels do not share exactly the same sensor
  orientation.
- **Creative effects** or thumbnail rotation before a final crop.

## How it works

The operator delegates to `scipy.ndimage.rotate` on the first two axes of the image (rows,
columns), leaving the color-channel axis untouched:

1. The output canvas is **sized** to enclose all four corners of the rotated image
   (`reshape=True`) — the final image is therefore larger than the original whenever the angle
   is not a multiple of 90°.
2. Each output pixel is obtained by **spline interpolation** of order `order` from the input
   pixels around its pre-image under the inverse rotation.
3. Canvas areas that map to no source pixel (the corners) are filled with **black**
   (`mode="constant"`, `cval=0.0`).
4. The result is finally **clipped** to `[0, 1]` and cast back to `float32`.

## Mathematics

Let $\theta$ be the rotation angle (converted to radians), $(c_x, c_y)$ the center of the input
image of size $W \times H$. For each output pixel $(x', y')$, its pre-image in the source image
is recovered through the inverse rotation:

$$
\begin{pmatrix} x \\ y \end{pmatrix}
= R(-\theta)\begin{pmatrix} x' - c_x' \\ y' - c_y' \end{pmatrix}
+ \begin{pmatrix} c_x \\ c_y \end{pmatrix},
\qquad
R(\theta) = \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
$$

where $(c_x', c_y')$ is the center of the output canvas. The pixel value is then obtained by
**spline interpolation of order `order`** around $(x, y)$ (order 0 = nearest neighbor, order 1 =
bilinear, higher orders = increasingly smooth splines, but more costly and more prone to ringing
around sharp edges such as saturated stars).

The size of the grown canvas is computed to enclose the bounding box of the rotated image:

$$
W' = \big\lceil\, |W\cos\theta| + |H\sin\theta| \,\big\rceil, \qquad
H' = \big\lceil\, |W\sin\theta| + |H\cos\theta| \,\big\rceil .
$$

## Parameters

- **`angle`** — *real*, default `0.0`, range `-360`–`360`. Rotation angle in degrees; positive
  = counterclockwise, around the image center.
- **`order`** — *int*, default `1`, range `0`–`5`. Order of the spline interpolation used to
  resample the rotated image (0 = nearest neighbor, 1 = bilinear, up to 5).

## Tips & pitfalls

> **Warning** — the output canvas is **grown**, and the uncovered corners are filled with black
> (value 0). If the image needs to stay rectangular with no black borders, follow up with `Crop`
> to keep only the largest rectangle inscribed in the useful content.

> **Note** — `is_maskable = False`: like any geometric transformation, rotation changes the data
> shape and cannot be combined with a blend mask (which assumes identical geometry before and
> after).

- A high interpolation order (3–5) smooths more but can introduce ringing artifacts around
  high-contrast stars; order 1 (bilinear) is often a good compromise for astro images.
- For exact 90°/180°/270° rotations or mirroring, prefer `FastRotation`: no interpolation, so
  no loss or blur.
- The final clipping to `[0, 1]` assumes an image already normalized to that range; on a
  high-dynamic-range linear image, check that no information is lost by the clip.

## See also

- [FastRotation](retina-doc://FastRotation) — lossless 90°/180°/270° rotations and mirroring.
- [Crop](retina-doc://Crop) — trim the black borders left by the rotation.
- [Resample](retina-doc://Resample) — scale-factor resampling, same interpolation family.
- [PixelInterpolation](retina-doc://PixelInterpolation) — interpolation settings shared by the geometric operators.

## References

- PixInsight — *Rotation* tool reference.
- scipy.ndimage.rotate — interpolated array rotation documentation.
