---
id: ArcsinhStretch
category: IntensityTransformations
title: Arcsinh Stretch
brief: Non-linear stretch based on the inverse hyperbolic sine, preserving color by acting on luminance.
keywords: [arcsinh, stretch, color, luminance, highlights, non-linear, saturation]
related: [HistogramTransformation, MaskedStretch, AutoHistogram, ExponentialTransformation]
icon: wave-sine
references:
  - "PixInsight — ArcsinhStretch tool reference."
  - "Lupton, R. et al. (2004) — Preparing Red-Green-Blue Images from CCD Data."
---

## Summary

`ArcsinhStretch` applies a non-linear stretch based on the **inverse hyperbolic sine**
(`asinh`), a function well known in scientific imaging for strongly compressing highlights
while staying almost linear near zero. Unlike a per-channel independent stretch, the stretch
factor here is computed **once from the luminance** and then re-applied to every RGB channel
through the same ratio: the relative proportions between channels are preserved, so **hues do
not drift toward white** as stars or a galaxy core approach saturation. This is a
**destructive** process (it rewrites pixel values), unlike the STF which only affects display.

## Use cases

- **Stretch a linear image** (fresh out of integration) while keeping faithful colors on
  high-contrast subjects (galaxy cores, bright stars, saturated HII regions).
- **Alternative to HistogramTransformation** when a classic MTF stretch turns stars white or
  desaturates the core of bright objects.
- **Reveal faint extensions** (tidal tails, diffuse nebulosity) without crushing already
  well-exposed areas, thanks to the smooth, progressive compression of `asinh`.
- **Scientific / photometric pipelines** where preserving inter-channel color ratios matters
  (Lupton-et-al.-style composites for RGB imaging).

## How it works

The operator works in two steps:

1. **Black-point removal**: pixels are linearly remapped from `black_point` up to `1.0`,
   clipped to `[0, 1]` — similar in spirit to the `shadows` remap of
   `HistogramTransformation`, but with no adjustable white point (it stays fixed at 1).
2. **Normalized arcsinh compression**: the remapped value is passed through
   `asinh(stretch · x) / asinh(stretch)`, a curve that equals 0 at 0 and 1 at 1, nearly linear
   for small values and strongly compressed for large ones — the higher `stretch`, the more
   aggressive the highlight compression.

For color images (≥ 3 channels), the curve is evaluated **only once, on the luminance**
(the mean of R, G, B). The ratio `stretched luminance / original luminance` then becomes a
common scale factor, multiplied unchanged into every channel. A saturated red pixel therefore
stays red (just brighter), instead of whitening as a per-channel stretch would. For a
mono/grayscale image, the curve is applied directly to the single channel.

## Mathematics

Let $x$ be a pixel value in $[0,1]$, $b$ = `black_point`, $k$ = `stretch` (with $k > 1$).
First compute the remapped value after black-point removal:

$$ x_n = \operatorname{clip}\!\left(\frac{x - b}{\,1 - b\,},\; 0,\; 1\right) $$

then the **normalized arcsinh stretch function**:

$$ f(x_n) = \frac{\operatorname{asinh}(k\, x_n)}{\operatorname{asinh}(k)} $$

This function maps $0 \mapsto 0$ and $1 \mapsto 1$. For small $x_n$, $\operatorname{asinh}$ is
nearly linear ($\operatorname{asinh}(u) \approx u$), so $f$ preserves faint tones
proportionally; for $x_n$ close to 1, $\operatorname{asinh}(u) \approx \ln(2u)$ when $k$ is
large, which **logarithmically compresses** the highlights instead of clipping them.

For color, with $L = \tfrac{1}{3}(R_n + G_n + B_n)$ the remapped luminance, a single scale
factor is computed:

$$ r = \frac{f(L)}{L} \qquad (L > \varepsilon) $$

and every channel is scaled by that same ratio, $C' = \operatorname{clip}(C_n \cdot r,\, 0,\,
1)$ for $C \in \{R, G, B\}$ — which guarantees $R'\!:\!G'\!:\!B' = R_n\!:\!G_n\!:\!B_n$, i.e.
hue and relative saturation are preserved.

## Parameters

- **`stretch`** — *real*, default `10.0`, range `1`–`1000`. Stretch factor (the $k$ in the
  formula). The higher it is, the more aggressive the highlight compression and the more the
  faint tones are relatively expanded. A value near 1 gives almost no stretch; useful values
  typically range from a few units up to several hundred.
- **`black_point`** — *real*, default `0.0`, range `0`–`1`. Black point: input level mapped to
  0 before the stretch. Anchors the sky background before compression, similar to the
  `shadows` slider of `HistogramTransformation`, but with no independent white-point control.

## Tips & pitfalls

> **Warning** — a very high `stretch` combined with a zero `black_point` can over-compress the
> whole image, leaving no perceptible contrast in the sky background. Set `black_point` first
> to anchor the background, then raise `stretch` progressively.

> **Note** — color preservation relies on the mean luminance of the three channels; on an
> image with a strongly dominant channel (severe white-balance imbalance), a prior
> `ColorCalibration` or `BackgroundNeutralization` gives better results.

- Unlike `HistogramTransformation`, there is no independent `midtones` slider: the entire
  curve shape is driven by `stretch` alone, which simplifies tuning but offers less fine
  control over the midpoint.
- For very bright stars still saturating despite `ArcsinhStretch`, combine it with a mask
  protecting the highlights (as in `MaskedStretch`) rather than pushing `stretch` to extremes.

## See also

- [HistogramTransformation](retina-doc://HistogramTransformation) — classic three-point MTF
  stretch (shadows/midtones/highlights).
- [MaskedStretch](retina-doc://MaskedStretch) — iterative stretch with active highlight
  protection via a mask.
- [AutoHistogram](retina-doc://AutoHistogram) — "baked" auto-stretch derived from the robust
  median, a good starting point before a fine `ArcsinhStretch` pass.
- [ExponentialTransformation](retina-doc://ExponentialTransformation) — another simple
  non-linear stretch (power law), without explicit color preservation.

## References

- PixInsight — *ArcsinhStretch* tool reference.
- Lupton, R. et al. (2004) — *Preparing Red-Green-Blue Images from CCD Data*.
