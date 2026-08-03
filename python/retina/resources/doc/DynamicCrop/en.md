---
id: DynamicCrop
category: Geometry
title: Dynamic Crop
brief: Crops a fractional [0,1] region of the image and rotates it, in a single pass — the cropped piece, or the tilted rectangle itself.
keywords: [crop, cropping, rotation, framing, composition, interpolation]
related: [Crop, Rotation, FastRotation, DynamicAlignment]
icon: crop
references:
  - "PixInsight — DynamicCrop tool reference."
  - "scipy.ndimage.rotate — image rotation with spline interpolation."
  - "scipy.ndimage.map_coordinates — sampling an image on an arbitrary grid."
---

## Summary

`DynamicCrop` combines a rectangular crop and a rotation into **a single operation**, mirroring
PixInsight's interactive tool of the same name. The crop rectangle is expressed in
**fractional coordinates** `[0, 1]` (independent of the image's resolution), and the rotation
angle is applied **after** the crop, to the extracted region. This is the final compositional
tool: framing a shot, straightening a horizon or aligning a galactic axis, and trimming the
ragged edges left over from stacking or registration.

![Before — DynamicCrop](figures/before.webp)
![After — DynamicCrop](figures/after.webp)

*The frame, and a rectangle drawn at 20 degrees read in a single pass. The output is exactly the size of the rectangle — the older mode, which rotates after cutting, enlarges the result and leaves black corners.*

## Use cases

- **Frame the final composition** of a stacked image, trimming dark or artifact-ridden edges
  left by `StarAlignment`/`Integration`.
- **Straighten an image** whose axis (horizon, galactic plane, trail) is not level, in a single
  crop + rotation pass instead of two separate processes.
- **Isolate a region of interest** (a galaxy, a cluster) before further processing, independent
  of the source image's pixel dimensions.
- Prepare a **cropped thumbnail** for publication, trimming edges after correcting a tilt.

## How it works

The rectangle is always read the same way: `x0, y0` (top-left corner) and `x1, y1` (bottom-right
corner) are fractions of the image width/height, rounded to pixel indices. Corners given inverted
(`x1 < x0` or `y1 < y0`) are normalized automatically; a zero width or height is forced to a
minimum of one pixel to avoid an empty crop.

What `angle` then means is decided by **`mode`**:

**`after_crop`** (default, and the historical behaviour). The axis-aligned rectangle is cut out
*first*, then the extracted piece is rotated with `scipy.ndimage.rotate`: **bilinear**
interpolation (order 1), `reshape=True` (the output canvas grows to fully contain the rotated
image without clipping it), and zero-fill (`mode="constant", cval=0.0`) for the corners now
outside the source region. If the angle is zero (within $10^{-9}$), the rotation is skipped and
only the crop is returned. The output is **clipped** to `[0, 1]`. Two consequences to keep in
mind: the output is **larger** than the rectangle, and its corners are **black**.

**`rotated_rect`** (PixInsight's behaviour). The rectangle *itself* is tilted, and the pixels it
covers are resampled in **one single pass** (`scipy.ndimage.map_coordinates`, order 1, zero-fill
outside the image). The output is **exactly** the size of the rectangle, and has no black corner
as long as the tilted rectangle stays inside the image. A single pass is not a detail: rotating
then cropping would apply the interpolation blur twice, and the first pass would have to cover a
wider area than the final result to avoid eating the corners.

Both modes share the **same sign convention**: a positive angle rotates the image content
counter-clockwise. Switching modes therefore never sends the image the other way. Note the
consequence in the interactive panel: in `rotated_rect` the handle tilts the *frame*, so tilting
it clockwise yields content rotated counter-clockwise — a frame turning over a photograph.

## Mathematics

Let the image have width $W$ and height $H$. The fractional corners are first ordered and
converted to integer indices:

$$
x_{\min} = \big\lfloor \min(x_0, x_1)\,W \big\rceil, \qquad
x_{\max} = \max\big(\lfloor \max(x_0, x_1)\,W \rceil,\; x_{\min} + 1\big),
$$

and similarly for $y_{\min}, y_{\max}$ with $H$ (where $\lfloor \cdot \rceil$ denotes rounding
to the nearest integer). The extracted region is $C = I[y_{\min}:y_{\max},\, x_{\min}:x_{\max}]$.

The rotation by angle $\theta$ = `angle` (in degrees) maps each output pixel $(x', y')$ back to
coordinates in $C$ via the inverse transform, centered on the image center:

$$
\begin{pmatrix} x \\ y \end{pmatrix}
=
\begin{pmatrix} \cos\theta & \sin\theta \\ -\sin\theta & \cos\theta \end{pmatrix}
\begin{pmatrix} x' - c'_x \\ y' - c'_y \end{pmatrix}
+
\begin{pmatrix} c_x \\ c_y \end{pmatrix},
$$

where $(c_x, c_y)$ is the center of $C$ and $(c'_x, c'_y)$ is the center of the enlarged output
canvas. The value at $(x, y)$, generally non-integer, is estimated by **bilinear interpolation**
(order-1 spline) from the four surrounding pixels of $C$; positions outside $C$ receive the
constant value $0$. The output canvas has dimensions
$W' = |\,\text{width}(C)\cos\theta| + |\text{height}(C)\sin\theta|$ and $H'$ symmetrically, so
the rotated region fits entirely within it (`reshape=True`).

In `rotated_rect` mode the output grid *is* the rectangle — $W' = W_C$, $H' = H_C$ — and the same
matrix is applied directly, around the rectangle's own centre:

$$
\begin{pmatrix} x \\ y \end{pmatrix}
=
\begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
\begin{pmatrix} u - c_u \\ v - c_v \end{pmatrix}
+
\begin{pmatrix} c_x \\ c_y \end{pmatrix},
$$

where $(u, v)$ runs over the output pixels, $(c_u, c_v) = \big(\frac{W_C - 1}{2},
\frac{H_C - 1}{2}\big)$ and $(c_x, c_y)$ is the same point in image coordinates. Centres are
taken on **pixel centres** ($\frac{n-1}{2}$) rather than on the edge ($\frac{n}{2}$): otherwise
at $\theta = 0$ the grid would land half a pixel away from the original samples and the two modes
would no longer agree. The samples are read by `map_coordinates` with order-1 (bilinear)
interpolation, channel by channel — interpolating across channels would blend the colours. No
clipping is applied: bilinear interpolation is a convex combination, it cannot overshoot its
inputs.

## Parameters

- **`x0`** — *real*, default `0.0`, range `0`–`1`. **Left** edge of the crop rectangle, as a
  fraction of the image width.
- **`y0`** — *real*, default `0.0`, range `0`–`1`. **Top** edge of the rectangle, as a fraction
  of the height.
- **`x1`** — *real*, default `1.0`, range `0`–`1`. **Right** edge of the rectangle, as a
  fraction of the width.
- **`y1`** — *real*, default `1.0`, range `0`–`1`. **Bottom** edge of the rectangle, as a
  fraction of the height.
- **`angle`** — *real*, default `0.0`, range `-360`–`360`. **Rotation** angle in degrees. `0`
  means no rotation (the result is then the crop alone), and both modes coincide exactly.
- **`mode`** — *enum*, default `after_crop`, choices: `after_crop`, `rotated_rect`. What the angle
  applies to: the **cropped region** (canvas grows, black corners) or the **crop rectangle**
  itself (output exactly the size of the rectangle). The default preserves recipes, projects and
  process icons saved before this parameter existed.

## Tips & pitfalls

> **Warning** — in `after_crop`, rotation enlarges the canvas (`reshape=True`) and fills the
> newly empty corners with **black** (`0.0`). If you want a final image without black edges,
> either switch to `rotated_rect`, which was made for exactly this, or crop again after rotating.

> **Note** — in `rotated_rect`, a rectangle that sticks out of the image is not an error: what
> lies outside is sampled as `0.0`. It is missing data, not a failure — but it *does* bring back
> the black edges the mode otherwise avoids.

> **Note** — the `x0/y0/x1/y1` coordinates are **fractional**, not pixel-based: the same
> `ProcessInstance` therefore applies identically to images of different resolutions (handy for
> a recipe replayed across several frames).

- Corners given in reversed order (`x1 < x0` or `y1 < y0`) are not an error: the rectangle is
  normalized silently — convenient for a GUI selection drag in any direction.
- For an angle that is a multiple of 90° with no interpolation loss or blur, prefer
  `FastRotation`, which swaps/flips axes rather than resampling.
- This process is **not maskable** (`is_maskable = False`): it changes the image geometry, so a
  mask (defined in pixels on the original geometry) would no longer be meaningful afterwards.

## See also

- [Crop](retina-doc://Crop) — crop alone, without rotation.
- [Rotation](retina-doc://Rotation) — rotation alone, without a prior crop.
- [FastRotation](retina-doc://FastRotation) — exact 90°/180°/270° rotations and flips, without interpolation.
- [DynamicAlignment](retina-doc://DynamicAlignment) — manual control-point registration (translation/rotation/scale).

## References

- PixInsight — *DynamicCrop* tool reference.
- scipy.ndimage — *rotate*, image rotation by spline interpolation.
- scipy.ndimage — *map_coordinates*, sampling an image on an arbitrary grid.
