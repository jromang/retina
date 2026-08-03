---
id: MultiscaleAdaptiveStretch
category: MultiscaleProcessing
title: Multiscale Adaptive Stretch
brief: "Multiscale adaptive stretch: global tonality stretched, local detail preserved."
keywords: [stretch, adaptive, starlet, multiscale, tonality, local contrast, HDR]
related: [AdaptiveStretch, MultiscaleLinearTransform, HDRMultiscaleTransform, HistogramTransformation]
icon: stack
references:
  - "PixInsight — AdaptiveStretch tool reference."
  - "Starck, J.-L. & Murtagh, F. — Astronomical Image and Data Analysis (à trous starlet transform)."
---

## Summary

`MultiscaleAdaptiveStretch` combines two complementary PixInsight ideas into a single process:
the **starlet** (à trous) wavelet decomposition of `MultiscaleLinearTransform` and the
**data-driven** transfer curve of `AdaptiveStretch`. The image is split into detail layers
(fine structures) and a large-scale residual (the global tonality). Only that residual receives
the adaptive stretch — the detail layers are added back afterward, with an adjustable gain. The
result: the global dynamic range unfolds (faint extensions revealed, highlights not crushed)
**without** local contrast being smoothed out or artificially amplified by the tonal curve, unlike
running `AdaptiveStretch` or `HistogramTransformation` directly on the full-resolution image.

![Before — MultiscaleAdaptiveStretch](figures/before.webp)
![After — MultiscaleAdaptiveStretch](figures/after.webp)

*Before, and after an adaptive stretch computed scale by scale over six layers.*

## Use cases

- **Reveal faint extensions** of a nebula or galaxy (tidal tails, halo) while keeping a detailed,
  non-saturated core.
- **Final stretch of a linear integration** when a plain `HistogramTransformation` crushes either
  fine detail or highlights depending on the midtones setting.
- **Selectively boost micro-contrast** (`detail_boost` > 1) after the tonality has been stretched,
  without redoing the whole stretch.
- Alternative to `HDRMultiscaleTransform` when a tonal curve **driven by the image's own local
  statistics** is preferred over a simple dynamic-range compression of the residual.

## How it works

For each channel, independently:

1. **Starlet decomposition** (`starlet_transform`, "à trous" B3-spline kernel) into `layers`
   detail layers $w_1, \dots, w_J$ plus a residual $c_J$ carrying the global (low-frequency)
   tonality.
2. The residual is normalized to $[0,1]$ and passed through `adaptive_stretch_channel` — the
   same algorithmic core as the `AdaptiveStretch` process: a monotone transfer curve is built
   from differences between neighboring pixels of the residual (`noise_threshold` separates real
   detail from residual noise, `contrast_protection` caps the curve's extreme slopes), then
   de-normalized.
3. The original detail layers are summed and multiplied by `detail_boost`, then added back to
   the stretched residual. The final image is clipped to $[0,1]$.

Because the adaptive curve is computed on the **smoothed** residual (low resolution) rather than
the raw image, the contrast votes are not polluted by pixel-level noise or fine structures — the
global tonality can therefore be stretched more aggressively without generating halos around
stars or amplified noise.

## Mathematics

**Starlet decomposition.** Let $I$ be a channel's image. The à trous transform builds a sequence
of smoothed approximations $c_0 = I, c_1, \dots, c_J$ by convolving with a B3-spline kernel
dilated by a factor $2^j$ at step $j$, and the detail layers by difference:

$$ w_j = c_{j-1} - c_j, \qquad j = 1, \dots, J, \qquad I = \sum_{j=1}^{J} w_j + c_J. $$

**Adaptive curve on the residual.** The normalized residual $r = (c_J - \min c_J)/(\max c_J - \min c_J)$
is discretized into $n$ intensity levels. For every pair of neighboring pixels $(a,b)$
(horizontal and vertical), the difference $|a-b|$ is compared to the threshold
$t = $ `noise_threshold` $\cdot(n-1)$: if $|a-b| > t$, the lower level of the pair receives a
"real detail" vote ($\mathrm{pos}$), otherwise a "noise" vote ($\mathrm{neg}$). The local slope
of the transfer curve is:

$$ \delta_k = \max\!\big(\mathrm{pos}_k - \mathrm{neg}_k,\; 0\big) + \varepsilon, \qquad k = 0, \dots, n-1, $$

with a floor $\varepsilon$ guaranteeing strict monotonicity. If `contrast_protection` $> 0$, the
slopes are capped at a quantile of $\{\delta_k > 0\}$ to avoid extreme contrast jumps. The final
curve is the normalized cumulative sum of the slopes:

$$ \mathrm{curve}(k) = \frac{\sum_{i=0}^{k}\delta_i - \delta_0}{\sum_{i=0}^{n-1}\delta_i - \delta_0}, \qquad
   r'(x,y) = \mathrm{curve}\big(\lfloor r(x,y)\,(n-1)\rfloor\big). $$

**Recomposition.** The stretched residual is rescaled back to its original range and combined
with the detail layers weighted by the gain $g = $ `detail_boost`:

$$ I'(x,y) = r'(x,y)\cdot(\max c_J - \min c_J) + \min c_J \;+\; g \sum_{j=1}^{J} w_j(x,y), $$

clipped to $[0,1]$ at the end.

## Parameters

- **`layers`** — *int*, default `5`, range `1`–`10`. Number of starlet detail layers preserved
  before the residual. More layers pull larger-scale spatial structure into the "detail" set
  (so less remains in the stretched residual); fewer layers leave more mid-scale structure in
  the residual that gets adaptively stretched.
- **`noise_threshold`** — *real*, default `0.001`, range `1e-06`–`0.5`. Threshold (in normalized
  intensity units) separating neighboring-pixel variations considered real detail from those
  considered noise, within the residual. Higher = a gentler curve (fewer places judged
  "detail-rich").
- **`contrast_protection`** — *real*, default `0.0`, range `0`–`1`. Caps the extreme slopes of
  the data-derived tonal curve. `0` = no protection (potentially very aggressive local
  contrast); near `1` = heavily smoothed curve.
- **`detail_boost`** — *real*, default `1.0`, range `0`–`4`. Multiplicative factor applied to
  the summed detail layers before they are added back. `1.0` = unchanged detail, `0` = detail
  removed (tonality only), `> 1` = boosted micro-contrast.

## Tips & pitfalls

> **Warning** — a high `detail_boost` (> 2) combined with a low `noise_threshold` also amplifies
> residual noise present in the fine layers. Denoise (`NoiseReduction`, or
> `MultiscaleLinearTransform` in thresholding mode) before stretching if noise is visible.

- Increase `layers` on fields rich in extended structure (diffuse nebulosity) so the residual
  properly captures global tonality without absorbing fine filaments.
- If the image still looks flat after stretching, lower `contrast_protection` rather than
  raising `detail_boost` — the latter only affects high frequencies, not the global dynamic
  range.
- Compare against plain `AdaptiveStretch` on a copy: if the two results are nearly identical,
  the image probably doesn't have enough multiscale structure to justify the extra complexity.

## See also

- [AdaptiveStretch](retina-doc://AdaptiveStretch) — the same stretching core, applied directly
  to the full-resolution image.
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — the starlet transform
  used here for the decomposition.
- [HDRMultiscaleTransform](retina-doc://HDRMultiscaleTransform) — alternative dynamic-range
  compression approach by scale.
- [HistogramTransformation](retina-doc://HistogramTransformation) — simple manual stretch, without
  multiscale decomposition.

## References

- PixInsight — *AdaptiveStretch* tool reference.
- Starck, J.-L. & Murtagh, F. — *Astronomical Image and Data Analysis* (à trous starlet transform).
