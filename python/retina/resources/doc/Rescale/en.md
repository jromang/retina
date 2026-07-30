---
id: Rescale
category: IntensityTransformations
title: Intensity Rescale
brief: Linearly renormalizes pixel values from their actual min/max range onto a target range.
keywords: [normalization, dynamic range, linear, min-max, renormalization, output range]
related: [HistogramTransformation, CurvesTransformation, Binarize, Statistics]
icon: arrows-maximize
references:
  - "PixInsight — Rescale tool reference."
---

## Summary

`Rescale` applies a **linear renormalization** to the image: it measures the actual minimum and
maximum of the samples, then stretches (or compresses) that range onto a user-chosen output
interval (`low`–`high`, default `[0, 1]`). Unlike `HistogramTransformation`, there is **no
clipping and no midtones curve**: it is a plain affine transform, fully determined by the
extrema found in the data.

## Use cases

- **Bring an image back into a displayable range** after an operation that produced values
  outside `[0, 1]` (convolution with a kernel that has negative weights, gradient-domain HDR
  composition, PixelMath, inverse FFT…).
- **Normalize the dynamic range** across several images before combining them (averaging,
  LRGB) when their value ranges differ.
- **Prepare an image for export** to an integer format (8/16-bit) that requires samples within
  `[0, 1]`.
- **Reserve headroom** by targeting a tighter output range (e.g. `[0.05, 0.95]`) to avoid
  clipping in subsequent additive steps.

## How it works

1. The minimum and maximum are computed **over the entire `(H, W, C)` array**, i.e. **jointly
   across all channels** — not per channel. This preserves the color balance of an RGB image:
   all three channels undergo exactly the same affine transform.
2. Each sample is linearly remapped from `[min, max]` to `[0, 1]`, then reprojected onto
   `[low, high]`.
3. Degenerate case: if the image is perfectly constant (`max == min`), the division by zero is
   avoided and the result is a uniform image at value `low` (typically 0).
4. The result is returned as `float32`.

## Mathematics

Let $x$ be a sample, $x_{\min}$ and $x_{\max}$ the **global** extrema of the array (all
channels combined), and $\ell$ = `low`, $u$ = `high` the output bounds. First the relative
position is computed:

$$ y = \frac{x - x_{\min}}{x_{\max} - x_{\min}} \qquad (x_{\max} > x_{\min}) $$

then reprojected onto the target range:

$$ x' = y \,(u - \ell) + \ell = \ell + (x - x_{\min})\,\frac{u - \ell}{x_{\max} - x_{\min}} $$

This is a **single affine transform** (same coefficients for every pixel and every channel):
$x_{\min} \mapsto \ell$ and $x_{\max} \mapsto u$, with no curvature and no intermediate
clipping. If $x_{\max} = x_{\min}$ (flat image) the quotient is undefined and the
implementation returns $x' = 0$ everywhere instead of dividing by zero.

## Parameters

- **`low`** — *real*, default `0.0`, range `0`–`1`. Lower bound of the output range: the
  input image's minimum value is mapped to `low`.
- **`high`** — *real*, default `1.0`, range `0`–`1`. Upper bound of the output range: the
  input image's maximum value is mapped to `high`.

## Tips & pitfalls

> **Warning** — the bounds come from the data's **actual** extrema: a single hot pixel or
> isolated artifact dominates the mapping and crushes the rest of the dynamic range toward
> black. Run `CosmeticCorrection` or `CosmicClip` before `Rescale` if the image contains
> defective pixels.

> **Warning** — on a perfectly constant image (synthetic test frame, uniform mask), `Rescale`
> silently returns an image entirely at `low`, wiping out any content instead of raising an
> error.

- The computation is **joint across all channels**: it does not correct an existing color
  imbalance, it preserves it. To normalize channels independently, use `ChannelExtraction` +
  `Rescale` + `ChannelCombination`.
- Swapping `low` and `high` (`low > high`) produces an inverted (negative) mapping on top of
  the renormalization — sometimes useful, sometimes accidental.
- With no midtones and no clipping, `Rescale` is purely linear: for a perceptual (gamma)
  stretch, use `HistogramTransformation` or `CurvesTransformation` instead or afterward.

## See also

- [HistogramTransformation](retina-doc://HistogramTransformation) — non-linear stretch with
  black/white point and midtones.
- [CurvesTransformation](retina-doc://CurvesTransformation) — free-curve tonal control.
- [Binarize](retina-doc://Binarize) — all-or-nothing thresholding after normalization.
- [Statistics](retina-doc://Statistics) — inspect min/max/median before choosing the bounds.

## References

- PixInsight — *Rescale* tool reference.
