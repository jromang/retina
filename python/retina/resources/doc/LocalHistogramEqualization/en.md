---
id: LocalHistogramEqualization
category: MultiscaleProcessing
title: Local Histogram Equalization
brief: Contrast-limited adaptive histogram equalization (CLAHE) to lift fine-scale contrast without crushing global tones.
keywords: [CLAHE, local contrast, equalization, adaptive histogram, enhancement, fine detail]
related: [HistogramTransformation, AdaptiveStretch, UnsharpMask, ACDNR]
icon: chart-histogram
references:
  - "Zuiderveld, K. — Contrast Limited Adaptive Histogram Equalization, Graphics Gems IV (1994)."
  - "scikit-image — skimage.exposure.equalize_adapthist."
---

## Summary

`LocalHistogramEqualization` applies **Contrast-Limited Adaptive Histogram Equalization**
(CLAHE) via `skimage.exposure.equalize_adapthist`. Unlike `HistogramTransformation`, which
applies a single transfer function to the whole image, this operator computes a **different
equalization function for each local region** of the image and smoothly interpolates between
neighboring regions. The result lifts contrast on fine structures (nebula filaments, galaxy
arms, lunar/planetary detail) without crushing global tones or blowing out the sky background.

## Use cases

- **Bring out faint structure** (filaments, nebula wisps) buried in low-contrast background
  where a global stretch alone falls short.
- **Planetary/lunar detail**: enhance relief and albedo nuances at local scale.
- **Complement a classic stretch** (`HistogramTransformation`, `AdaptiveStretch`) with a local
  contrast pass at the end of processing, for extra "punch" without halo artifacts.
- Alternative to `UnsharpMask`/`ACDNR` when the goal is perceptual contrast gain rather than
  convolution-based sharpening.

## How it works

Processing is applied **independently per channel** (R, G, B, or mono luminance):

1. The channel values are first **clipped to `[0, 1]`** (the image must be normalized float).
2. The image is tiled into a grid of **contextual regions** whose size is set by `kernel_size`
   (or computed automatically by scikit-image, roughly 1/8 of each image dimension, when
   `kernel_size = 0`).
3. Within each tile, a **local histogram** is computed and then **clipped**: any bin exceeding
   a threshold derived from `clip_limit` has its excess redistributed uniformly across the other
   bins — this is what prevents noise amplification in near-uniform regions (sky background).
4. Each tile's **transfer function** is the CDF (cumulative distribution function) of its
   clipped histogram.
5. Each pixel's final value is obtained by **bilinear interpolation** between the transfer
   functions of the four nearest neighboring tiles, which removes visible discontinuities at
   tile boundaries.

## Mathematics

For a tile $R$ containing $N_R$ pixels of the channel, let $h_R(k)$ be the histogram over
$n_\text{bins}$ levels $k = 0,\dots,n_\text{bins}-1$. Clipping caps each bin at a ceiling $c$
proportional to `clip_limit`:

$$ c = \texttt{clip\_limit} \cdot \frac{N_R}{n_\text{bins}}, \qquad
   h_R^{\text{clip}}(k) = \min\!\big(h_R(k),\, c\big), $$

and the total excess $\sum_k \big(h_R(k) - h_R^{\text{clip}}(k)\big)$ is redistributed uniformly
over the $n_\text{bins}$ bins. The local transfer function is the normalized CDF of the result:

$$ T_R(x) = \frac{1}{N_R}\sum_{k=0}^{x} h_R^{\text{clip,redist}}(k). $$

For a pixel with value $x$ located between the centers of four neighboring tiles
$R_{00}, R_{10}, R_{01}, R_{11}$, with bilinear weights $(u, v) \in [0,1]^2$ derived from its
position, the output value is:

$$ y = (1-u)(1-v)\,T_{R_{00}}(x) + u(1-v)\,T_{R_{10}}(x)
     + (1-u)v\,T_{R_{01}}(x) + uv\,T_{R_{11}}(x). $$

The smaller `clip_limit` is, the lower $c$ is and the more local contrast amplification is
contained (the histogram is barely changed as `clip_limit → 0`); the closer to 1, the closer the
equalization gets to plain per-tile histogram equalization, with a growing risk of amplifying
noise heavily.

## Parameters

- **`clip_limit`** — *real*, default `0.01`, range `0.0`–`1.0`. Normalized clipping threshold for
  the local histogram. A low value strongly limits contrast (and noise) amplification; a high
  value allows more aggressive equalization at the cost of more visible local noise.
- **`kernel_size`** — *int*, default `0`, range `0`–`1024`. Size (in pixels) of the contextual
  tiles used to compute local histograms. `0` lets scikit-image pick an automatic size
  (~1/8 of each image dimension). A small tile follows fine-scale variation closely (but can
  create halos); a large tile approaches a global stretch.

## Tips & pitfalls

> **Warning** — too high a `clip_limit` strongly amplifies background noise, especially in
> low-texture sky areas: start from the default (`0.01`) and increase gradually while watching
> the background.

> **Note** — CLAHE acts **per channel** independently; on a color image this can slightly shift
> the local color balance. Check the color rendering after applying, or work on a separate
> luminance channel (`ComponentSeparation`) if needed.

- Too small a `kernel_size` can produce artificial halos around stars or high-contrast edges:
  increase the tile size if such artifacts appear.
- This operator is **destructive** (it rewrites pixels): apply it after a reasonable stretch,
  never directly on raw linear data.
- Combine it with a star mask to spare star cores, which are often sensitive to local
  equalization effects.

## See also

- [HistogramTransformation](retina-doc://HistogramTransformation) — global tonal stretch (MTF).
- [AdaptiveStretch](retina-doc://AdaptiveStretch) — multiscale-adaptive background stretch.
- [UnsharpMask](retina-doc://UnsharpMask) — sharpening via blurred-mask convolution.
- [ACDNR](retina-doc://ACDNR) — adaptive noise reduction with local contrast preservation.

## References

- Zuiderveld, K. — *Contrast Limited Adaptive Histogram Equalization*, Graphics Gems IV (1994).
- scikit-image — *skimage.exposure.equalize_adapthist*.
