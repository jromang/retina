---
id: AdaptiveStretch
category: IntensityTransformations
title: Adaptive Stretch
brief: "Non-linear stretch built automatically from the differences between neighboring pixels (PixInsight's AdaptiveStretch)."
keywords: [stretch, adaptive, contrast, noise, transfer curve, luminance, MaskedStretch]
related: [MaskedStretch, HistogramTransformation, MultiscaleAdaptiveStretch, ArcsinhStretch]
icon: adjustments
references:
  - "PixInsight — AdaptiveStretch tool reference."
  - "Conejero, J. — AdaptiveStretch: a data-driven, contrast-adaptive non-linear stretch."
---

## Summary

`AdaptiveStretch` builds a **non-linear transfer curve** directly from the image content,
without placing any point by hand. It examines the intensity differences between neighboring
pixels: wherever those differences exceed a noise threshold, it infers **real detail** and
dilates the corresponding tonal range; wherever they stay below it, it assumes **noise** and
compresses that range instead. The result is a stretch that selectively boosts contrast in
structured areas (nebulosity, galaxy arms) without amplifying sky-background grain. It is a
**destructive** process: pixel values are rewritten into the view's history.

## Use cases

- **Stretch a linear image** while preserving faint diffuse structure without lifting the
  sky-background noise.
- **Hands-off alternative** to `HistogramTransformation`/`CurvesTransformation` when you want a
  first, data-driven pass instead of a hand-drawn curve.
- **Boost local contrast** of faint nebulae or galaxies before fine-tuning with curves.
- **Compare several noise thresholds** to find the detail/noise trade-off matching the actual
  SNR of the exposure.

## How it works

1. Each pixel's intensity is **discretized** into `resolution` integer levels in
   `[0, resolution-1]`.
2. For every pair of **adjacent** pixels (right and bottom neighbors), the absolute difference
   between their levels is computed. If that difference exceeds `noise_threshold` (converted to
   discrete levels), the pair **votes to dilate** the lower of the two intensity levels;
   otherwise it **votes to compress** it.
3. These votes, accumulated over the whole image, form an estimate of the transfer curve's
   **local slope** at each level: `slope = max(dilation_votes - compression_votes, 0)`. The
   slope is therefore always non-negative, which guarantees a **monotonic** curve.
4. If `contrast_protection > 0`, the most extreme slopes are capped (clipped to a quantile),
   preventing a handful of very sharp transitions from dominating the whole curve and producing
   harsh contrast halos.
5. The final curve is obtained by **integrating** (cumulative sum) the slopes and renormalizing
   into `[0, 1]`; it is applied to each pixel by interpolation on its discrete level.
6. In color, the curve is computed **once, from luminance** (mean of R, G, B), then applied to
   each channel through a simple **scale ratio** — hue is therefore preserved, only brightness
   changes.

## Mathematics

Let $x \in [0,1]$ be a pixel's intensity (or luminance, in color) and $n$ = `resolution`.
Discretize it as:

$$ k(x) = \operatorname{clip}\!\big(\lfloor x\,(n-1) \rfloor,\; 0,\; n-1\big) \in \{0,\dots,n-1\}. $$

For every pair of adjacent pixels $(a, b)$ (horizontal and vertical neighbors), let
$\ell = \min(k_a, k_b)$ and $d = |k_a - k_b|$, and compare $d$ to the discrete threshold
$\tau = \texttt{noise\_threshold} \cdot (n-1)$:

$$
\begin{cases}
\text{pos}[\ell] \mathrel{+}= 1 & \text{if } d > \tau \quad\text{(real detail)} \\
\text{neg}[\ell] \mathrel{+}= 1 & \text{if } d \le \tau \quad\text{(noise)}
\end{cases}
$$

The curve's local slope at level $\ell$ is:

$$ \delta[\ell] = \max\big(\text{pos}[\ell] - \text{neg}[\ell],\; 0\big) + \varepsilon, $$

where $\varepsilon$ (a small floor) guarantees strictly positive growth. With
`contrast_protection` $= p \in [0,1]$, the non-zero slopes are capped at the quantile
$q_{1 - 0.99\,p}$ of their own distribution before adding $\varepsilon$. The transfer curve is
obtained by integration and renormalization:

$$ C(\ell) = \frac{\sum_{i=0}^{\ell} \delta[i] \;-\; \delta[0]}{\displaystyle\sum_{i=0}^{n-1} \delta[i] \;-\; \delta[0]}, \qquad
   y = C\big(k(x)\big). $$

In color, the curve $C$ is derived from luminance $L = (R+G+B)/3$, then applied by uniform
scaling of the three channels:

$$ (R', G', B') = (R, G, B) \cdot \frac{C(k(L))}{L}, \qquad L > 0. $$

This ratio preserves the pixel's hue and saturation exactly: only its intensity changes.

## Parameters

- **`noise_threshold`** — *real*, default `0.001`, range `1e-06`–`0.5`. Threshold (as a
  fraction of the `[0,1]` range) above which a difference between neighboring pixels is
  considered real detail rather than noise. Lower values make the curve dilate small
  variations more aggressively — risking amplified background noise; higher values keep the
  stretch more conservative.
- **`contrast_protection`** — *real*, default `0.0`, range `0.0`–`1.0`. Caps the curve's most
  extreme slopes to limit local over-contrast (halos around stars or sharp edges). `0` = no
  protection; near `1` = a very low cap, nearly-linear curve.
- **`resolution`** — *int*, default `4096`, range `64`–`65536`. Number of discrete levels of
  the transfer curve. A higher resolution gives a finer curve (fewer visible steps) but costs
  more memory and computation; a lower resolution can introduce visible banding on images with
  a wide dynamic range.

## Tips & pitfalls

> **Warning** — too low a `noise_threshold` amplifies sky-background noise just as much as
> real signal: if the background turns grainy after applying the stretch, raise the threshold
> or denoise first (`NoiseReduction`, `WaveletDenoise`).

> **Note** — the algorithm scans every pair of neighboring pixels in the image: on very large
> images, a high `resolution` increases computation time without necessarily improving the
> visual result — start from the default value.

- If contrast halos appear around stars or sharp edges, raise `contrast_protection` rather than
  lowering `noise_threshold` further.
- Since it is destructive, apply `AdaptiveStretch` on a copy or once the composition
  (registration, calibration) is finalized: it cannot be undone like an STF.
- For an iterative stretch with explicit highlight protection instead of noise-based shaping,
  prefer `MaskedStretch`.

## See also

- [MaskedStretch](retina-doc://MaskedStretch) — iterative stretch protecting the highlights.
- [HistogramTransformation](retina-doc://HistogramTransformation) — manual black/mid/white point stretch.
- [MultiscaleAdaptiveStretch](retina-doc://MultiscaleAdaptiveStretch) — multiscale variant of the same principle.
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — color-preserving arcsinh stretch.

## References

- PixInsight — *AdaptiveStretch* tool reference.
- Conejero, J. — *AdaptiveStretch: a data-driven, contrast-adaptive non-linear stretch*.
