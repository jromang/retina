---
id: MultiscaleMedianTransform
category: MultiscaleProcessing
title: Multiscale Median Transform
brief: "Non-linear decomposition via à-trous median filters (MMT): denoising and enhancement with better edge preservation than the linear wavelet transform."
keywords: [multiscale, median, a-trous, wavelet, denoising, edge preservation, MMT]
related: [MultiscaleLinearTransform, WaveletDenoise, ACDNR, NoiseReduction]
icon: stack
references:
  - "PixInsight — MultiscaleMedianTransform tool reference."
  - "Starck, J.-L., Murtagh, F. — Astronomical Image and Data Analysis (median multiresolution)."
---

## Summary

`MultiscaleMedianTransform` (MMT) decomposes the image into a stack of detail layers plus a
residual, exactly like `MultiscaleLinearTransform` (the starlet transform), but replaces the
linear B3-spline-kernel convolution at each scale with an **à-trous median filter**. Because the
median filter is non-linear and resistant to outliers, the resulting decomposition **preserves
sharp edges better** (star boundaries, junctions between structures) and produces **fewer
ringing artifacts** around high-contrast objects than its linear counterpart. It is the tool of
choice when classic wavelet denoising or enhancement leaves visible halos.

## Use cases

- **Denoise the sky background** by attenuating/thresholding the finest detail layer
  (pixel-to-pixel noise) without blurring star edges, unlike a global Gaussian blur.
- **Enhance structures at a given scale** (nebula filaments, galaxy arms) by selectively
  boosting one layer via `bias`, without lifting the noise of the other scales.
- **Alternative to `MultiscaleLinearTransform`** when it produces bright/dark rings around
  saturated stars or very high-contrast edges.
- **Prepare a clean base** before stretching (`AdaptiveStretch`, `HistogramTransformation`) by
  removing the fine-layer noise while still in linear space.

## How it works

For each channel, the algorithm builds an **à-trous** (undecimated, like the starlet) pyramid,
but with a median estimator instead of a convolution:

1. At scale $j$ (starting from $j=0$), the current image $c_j$ is filtered with a **dilated
   median filter**: the filter footprint is $(2s+1)\times(2s+1)$ with $s = 2^{j}$, but only the
   pixels spaced $s$ apart (the "holes") actually participate in the median computation —
   exactly the à-trous trick of the starlet transform, applied here to a median estimator
   instead of a convolution.
2. The **detail layer** $j$ is the difference between the image before and after this median
   filtering: $w_j = c_j - c_{j+1}$.
3. This is repeated `scales` times, doubling the dilation step each iteration, probing
   structures of increasing size without ever downsampling the image (full resolution is kept
   at every scale).
4. What remains is a **residual** $c_J$ (the image smoothed at the coarsest scale), carrying the
   overall tonal level.
5. Optionally, the finest layer ($j=0$, dominated by read/photon noise) undergoes **soft
   thresholding** controlled by `noise_threshold`, then every layer is multiplied by its
   **bias** (`bias`) before recombination.
6. **Reconstruction** is a simple telescoping sum: weighted details plus residual give back the
   image (exactly, if bias = 1 and threshold = 0).

## Mathematics

Let $M_s$ denote the à-trous median filtering operator with step $s$ (dilated footprint of size
$2s+1$, sampled every $s$ pixels). The pyramid is built recursively:

$$ c_0 = I, \qquad c_{j+1} = M_{2^{j}}(c_j), \qquad w_j = c_j - c_{j+1}, \quad j = 0,\dots,J-1, $$

where $J$ = `scales`. Unlike the starlet transform (where $M$ is a linear convolution, so the
sum trivially reconstructs the input algebraically), the median is non-linear — reconstruction
is nevertheless **exact by construction**, since each $w_j$ is defined as a telescoping
difference:

$$ I = \sum_{j=0}^{J-1} w_j + c_J. $$

Denoising applies **soft thresholding** to the finest layer, with a threshold derived from the
robust standard deviation (`mad_std`, made consistent with a normal distribution via the
$1.4826$ factor):

$$ t = \texttt{noise\_threshold} \cdot \operatorname{mad\_std}(w_0), \qquad
   \tilde w_0 = \operatorname{sign}(w_0)\cdot \max\!\big(|w_0| - t,\; 0\big). $$

Each layer is then weighted by its bias $b_j$ (`bias[j]`, or $1$ by default) before
recombination:

$$ I' = \sum_{j=0}^{J-1} b_j\, \tilde w_j \;+\; c_J, \qquad \text{then clipped to } [0,1]. $$

Setting $b_j = 0$ for all fine layers and $b_j = 1$ for coarse ones yields pure multiscale
median smoothing; raising a given $b_j > 1$ selectively amplifies scale $j$.

## Parameters

- **`scales`** — *int*, default `4`, range `1`–`10`. Number of detail layers (hence à-trous
  median filtering passes). More layers probe larger structures, at the cost of growing compute
  time (the median filter footprint grows with each scale).
- **`bias`** — *floatlist*, default `[]`. Multiplier applied to each detail layer before
  recombination (`bias[0]` for the finest layer, and so on). Scales beyond the list's length
  keep a bias of `1.0` (faithful reconstruction). An empty list leaves every layer unchanged.
- **`noise_threshold`** — *real*, default `0.0`, range `0`–`10`. Denoising threshold (in
  multiples of `mad_std`) applied **only to the finest layer** (scale 1, dominated by noise).
  `0` disables thresholding; useful values typically range from `1` to `4`.

## Tips & pitfalls

> **Warning** — the median filter is significantly more expensive than a convolution: on large
> images with many scales, `MultiscaleMedianTransform` runs slower than
> `MultiscaleLinearTransform`. Reserve it for cases where linear ringing is a real problem.

- Soft thresholding only affects the first layer (`j=0`): to denoise coarser scales, adjust
  their `bias` directly instead (e.g. `bias=[1, 0.5]` halves the second layer).
- Always compare against `MultiscaleLinearTransform` on the same image: the median wins on sharp
  edges (stars, planetary limbs) but may smooth pure Gaussian-noise regions slightly less well,
  where the B3-spline weighted average is optimal.
- To target a single structure (filaments, lace-like detail), isolate its layer by setting the
  other biases to `0` so you can inspect exactly what it contains before choosing the final gain.

## See also

- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — the same à-trous
  decomposition, but with a linear B3-spline kernel (starlet).
- [WaveletDenoise](retina-doc://WaveletDenoise) — denoising via classic discrete wavelets.
- [ACDNR](retina-doc://ACDNR) — adaptive noise reduction with edge preservation.
- [NoiseReduction](retina-doc://NoiseReduction) — generic single-scale denoising.

## References

- PixInsight — *MultiscaleMedianTransform* tool reference.
- Starck, J.-L., Murtagh, F. — *Astronomical Image and Data Analysis* (median multiresolution).
