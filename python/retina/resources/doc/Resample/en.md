---
id: Resample
category: Geometry
title: Resample
brief: Resizes the image by a continuous scale factor using spline interpolation.
keywords: [resample, resize, interpolation, spline, anti-aliasing, scale]
related: [IntegerResample, Crop, Rotation, PixelInterpolation]
icon: arrows-maximize
references:
  - "PixInsight — Resample tool reference."
  - "scikit-image — skimage.transform.resize (spline interpolation, anti-aliasing)."
---

## Summary

`Resample` changes the image size according to a **continuous scale factor** (`scale`),
recomputing every output pixel through **spline interpolation** at the chosen order. Unlike
`IntegerResample`, which only handles integer factors via binning/replication, `Resample`
accepts any real factor between `0.01` and `20.0` — upscaling or downscaling — and smooths the
result with automatic anti-aliasing when reducing size.

## Use cases

- **Downscale a final image** before web export or sharing (e.g. `scale = 0.5`).
- **Match the resolution** of several images intended for a mosaic or an LRGB combination whose
  channels were not sampled at the same scale.
- **Enlarge a crop** to closely inspect a region (e.g. a galaxy core) without losing smoothness
  of interpolation.
- Adapt a reference image's size before a downstream process that assumes specific dimensions
  (measurements, visual comparison).

## How it works

The process delegates all the work to `skimage.transform.resize`:

1. New dimensions are computed by rounding `height × scale` and `width × scale` to the nearest
   integer (minimum 1 pixel).
2. If the factor shrinks the image (`scale < 1.0`), an **anti-aliasing filter** (a preliminary
   Gaussian smoothing) is applied automatically to prevent frequency aliasing (moiré, jagged
   edges) before subsampling.
3. The image is **spline-interpolated** at order `order` on the new coordinate grid, using
   `reflect` boundary mode (pixels outside the frame are extrapolated by mirror symmetry).
4. The result is cast back to `float32`.

The operation changes the image's geometry (new dimensions): `is_maskable = False`, since a
blend mask assumes an identical shape and therefore does not apply here.

## Mathematics

Let the input image have dimensions $(H, W)$ and a scale factor $\lambda$ = `scale`. The output
dimensions are:

$$ H' = \max(1, \operatorname{round}(H\lambda)), \qquad W' = \max(1, \operatorname{round}(W\lambda)). $$

For every output pixel $(i', j')$, the corresponding position in the input image's coordinate
frame is:

$$ (i, j) = \left(\frac{i' + 0.5}{H'/H} - 0.5,\; \frac{j' + 0.5}{W'/W} - 0.5\right), $$

which is then evaluated on a **B-spline** of degree `order` ($n \in \{0,\dots,5\}$) fitted to the
input pixel grid:

- $n = 0$: nearest-neighbor (blocky output, no blur).
- $n = 1$: bilinear interpolation (default).
- $n = 3$: bicubic interpolation (softer smoothing, slight overshoot possible).
- $n = 5$: quintic spline (smoothest, most expensive).

When $\lambda < 1$, a Gaussian pre-filter of width $\sigma \propto (1/\lambda - 1)$ is applied
before sampling: this convolves the image with a low-pass kernel whose cutoff frequency follows
the Nyquist–Shannon theorem for the new grid, removing spatial-frequency components above
$1/(2\lambda)$ pixels$^{-1}$ and preventing them from folding back into low-frequency artifacts
after subsampling.

## Parameters

- **`scale`** — *real*, default `0.5`, range `0.01`–`20.0`. Scale factor applied to both
  dimensions: `< 1` shrinks the image, `> 1` enlarges it, `1` leaves it unchanged (copy).
- **`order`** — *int*, default `1`, range `0`–`5`. Order of the interpolation spline (0 =
  nearest-neighbor, 1 = bilinear, 3 = bicubic, 5 = quintic). A higher order smooths more but
  costs more and can introduce slight overshoot near sharp edges (stars, contours).

## Tips & pitfalls

> **Warning** — extreme factors (`scale` near `0.01` or `20.0`) produce tiny or huge images in
> memory; check the resulting size before batch-processing a whole set.

- For an **exact integer factor** (2×, 3×…), prefer `IntegerResample`: averaged binning
  (`downsample_op = "average"` or `"sum"`) preserves noise and photometric flux better than the
  generic spline interpolation used by `Resample`.
- `order = 0` is useful for resampling **binary masks** or defect maps without creating unwanted
  intermediate values.
- Upscaling (`scale > 1`) does not add real information: it does not substitute for genuine extra
  resolution (drizzle, super-resolution).

## See also

- [IntegerResample](retina-doc://IntegerResample) — binning/replication by an integer factor, preserves flux.
- [Crop](retina-doc://Crop) — cropping without scale change.
- [Rotation](retina-doc://Rotation) — rotation by an arbitrary angle, same interpolation family.
- [PixelInterpolation](retina-doc://PixelInterpolation) — interpolation settings shared by geometric processes.

## References

- PixInsight — *Resample* tool reference.
- scikit-image — *skimage.transform.resize* (spline interpolation, anti-aliasing).
