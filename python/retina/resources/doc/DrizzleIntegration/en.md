---
id: DrizzleIntegration
category: ImageIntegration
title: Drizzle Integration
brief: Upsamples and combines dithered frames to reconstruct sub-pixel detail.
keywords: [drizzle, upsampling, pixfrac, dithering, integration, sub-pixel]
related: [Integration, StarAlignment, FastIntegration, Resample]
icon: droplet
references:
  - "Fruchter, A. S. & Hook, R. N. — Drizzle: A Method for the Linear Reconstruction of Undersampled Images (2002)."
  - "PixInsight — ImageIntegration (drizzle mode) / DrizzleIntegration tool reference."
  - "scikit-image — skimage.transform.resize."
---

## Summary

`DrizzleIntegration` reconstructs an image at a **higher** resolution than the individual
subs by combining several frames that are slightly offset from one another (**dithering**).
It is a **global** process: it reads a list of already-registered files and creates a new
window, similar to `Integration`, but on a grid upsampled by a factor of `scale`.

## Use cases

- **Recover sub-pixel detail** from a series of images acquired with a small mount offset
  between exposures (deliberate dithering).
- **Compensate undersampling** (pixels too coarse relative to seeing/optics, or binning) by
  reconstructing a final image finer than the input subs.
- **Mosaics and wide fields** where a higher-resolution output is desired from many short
  exposures.

## How it works

Each frame in the `frames` list is loaded, then **projected onto an enlarged grid** by a
factor of `scale` per dimension (an `H×W` image becomes `sH×sW`). This implementation uses
**nearest-neighbor** resampling (`skimage.transform.resize`, `order=0`, no anti-aliasing):
each source pixel is simply replicated into a `scale×scale` block on the output grid — this
is the *pragmatic* variant of drizzle, without an explicit footprint calculation of the
shrunken "drop" at an arbitrary sub-pixel position.

Each upsampled frame receives a **weight** equal to `pixfrac²` (the area of the shrunken drop
is proportional to the square of the pixel fraction). The weighted frames are accumulated and
then divided by the sum of weights: the result is a **weighted average** on the upsampled
grid.

> **Note** — the process assumes the frames are **already registered** (see `StarAlignment`)
> with genuine sub-pixel precision between exposures (dithering). Without a sub-pixel
> variation of the pointing from one exposure to another, nearest-neighbor enlargement merely
> magnifies the pixel — no new detail appears, unlike classic drizzle, which redistributes
> each source pixel to its exact sub-pixel position on the output grid.

## Mathematics

Let $s$ be the `scale` factor and $f$ the pixel fraction `pixfrac` $\in [0.1, 1.0]$. For a
source frame $I_i$ of size $H \times W$, the nearest-neighbor enlargement operator produces
$U_i$ of size $sH \times sW$:

$$ U_i(y, x) = I_i\!\left(\left\lfloor \frac{y}{s} \right\rfloor,\ \left\lfloor \frac{x}{s} \right\rfloor\right). $$

The weight assigned to frame $i$ is the area of the shrunken drop:

$$ w_i = f^2. $$

The integrated image is the weighted average of the enlarged frames:

$$ D(y, x) = \frac{\sum_{i=1}^{N} w_i\, U_i(y, x)}{\sum_{i=1}^{N} w_i}
           = \frac{\sum_{i=1}^{N} U_i(y, x)}{N} \quad \text{(all weights being equal here),} $$

with the denominator floored at $10^{-6}$ to avoid a division by zero. In the original
Fruchter & Hook drizzle, $w_i$ and the accumulation position vary **per output pixel**
according to the exact geometric overlap between the shrunken drop (size $f \times f$ source
pixel) and each output-grid cell; here, absent an explicit per-frame sub-pixel transform, the
weight is **constant** and uniform across the whole image — so the actual detail
reconstruction depends entirely on the quality of the upstream sub-pixel registration.

## Parameters

- **`frames`** — *pathlist*, default `[]`. List of already-registered frame files (see
  `StarAlignment`) to integrate.
- **`scale`** — *int*, default `2`, range `1`–`4`. Upsampling factor of the output grid
  relative to the input frames (2 = output image twice as large in width and height).
- **`pixfrac`** — *real*, default `1.0`, range `0.1`–`1.0`. Pixel fraction (size of the
  shrunken drop); weights each frame by `pixfrac²`. A value near `1.0` is equivalent to a
  plain averaged upsampling; lower values concentrate the weight more (useful in classic
  drizzle to sharpen resolution, at the cost of more noise).
- **`new_image_id`** — *str*, default `"drizzle"`. Identifier of the created result window.

## Tips & pitfalls

> **Warning** — this implementation does **not** perform per-output-pixel sub-pixel
> splatting: it enlarges each frame by nearest neighbor and then averages. The actual
> resolution gain therefore depends entirely on the effective **dithering** between exposures
> and the precision of registration (`StarAlignment`), not just on the `scale`/`pixfrac`
> settings.

- Without dithering (frames aligned on the same integer pixel grid), prefer `Integration`
  followed by a plain `Resample`: drizzle will add nothing.
- A high `scale` (3 or 4) on few frames dilutes the signal per output pixel and amplifies
  visible noise; reserve it for series with many well-dithered exposures.
- Low `pixfrac` needs more frames to uniformly fill the output grid, or risks gaps or
  irregular coverage noise.

## See also

- [Integration](retina-doc://Integration) — classic stacking with robust sigma rejection.
- [StarAlignment](retina-doc://StarAlignment) — prerequisite registration step for drizzle.
- [FastIntegration](retina-doc://FastIntegration) — fast stacking variant without drizzle.
- [Resample](retina-doc://Resample) — generic resizing of an already-integrated image.

## References

- Fruchter, A. S. & Hook, R. N. — *Drizzle: A Method for the Linear Reconstruction of
  Undersampled Images* (2002).
- PixInsight — *ImageIntegration* (drizzle mode) / *DrizzleIntegration* tool reference.
- scikit-image — *skimage.transform.resize*.
