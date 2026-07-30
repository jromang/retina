---
id: MaskedStretch
category: IntensityTransformations
title: Masked Stretch
brief: "Iterative non-linear stretch that protects highlights by building a brightness-derived mask on the fly."
keywords: [stretch, MTF, highlights, star protection, iterative, non-linear, non-linear stretch]
related: [HistogramTransformation, ArcsinhStretch, AutoHistogram, AdaptiveStretch]
icon: ghost
references:
  - "PixInsight — MaskedStretch tool reference."
  - "Conejero, J. — Midtones Transfer Function (MTF)."
---

## Summary

`MaskedStretch` stretches a linear image into a display-ready one by repeating, iteration
after iteration, a small **MTF** stretch step whose strength is weighted by a protection mask
derived from the **pixel's own brightness**: the brighter a pixel already is, the less stretch
it receives. It is the equivalent of PixInsight's `MaskedStretch` tool — a practical
alternative to a classic stretch plus a manual star mask, useful when you want to bring the
sky background up to a target level without blowing out star cores or clipping highlights.

## Use cases

- **First stretch** of a linear image (after calibration/integration), to bring the sky
  background close to a target level while keeping stars compact.
- **Alternative to `HistogramTransformation` + a manual star mask**: the protection mask is
  computed automatically here, with no need for `StarMask`.
- **Star-dense fields** (clusters, star-rich regions) where a global stretch would massively
  bloat and clip stellar cores.
- Preparatory step before fine refinement with `CurvesTransformation` or
  `HistogramTransformation`.

## How it works

At each iteration, independently per channel:

1. The channel's current **median** is measured — a robust estimator of the sky background
   level.
2. If that median is already at or above the target background (`target_background`), or is
   zero, the channel is left untouched for this iteration (nothing to stretch, or nothing
   valid to stretch).
3. Otherwise, the `midtones` parameter of the **MTF** (Midtones Transfer Function, the same
   model used by `HistogramTransformation`/STF) is computed so that it maps this exact median
   onto the target, and that MTF is applied to the whole channel to obtain a `stretched`
   version.
4. The original and the stretched version are blended pixel by pixel with a **protection
   weight equal to `1 - pixel value`**: a dark pixel (near 0) receives almost 100% of the
   stretch, while an already-bright pixel (near 1, typically a star core) receives almost none
   and stays close to its original value.

Repeating this cycle (20 times by default) progressively converges the sky background toward
the target while highlights stay contained — hence the "masked" name: the protection mask is
not an external image (no `StarMask` needed), it is rebuilt on every pass from the pixels'
current brightness.

> **Note** — the process's `is_maskable` flag (as for any process) additionally allows a
> **real view mask** to be applied on top of this internal mechanism; the two forms of
> protection stack if needed.

## Mathematics

Let $x \in [0,1]$ be a channel pixel value at a given iteration, $\tilde{x}$ its median, and
$t$ = `target_background`. If $\tilde{x} \le 0$ or $\tilde{x} \ge t$, the channel is left
unchanged at this iteration.

Otherwise, we look for the midtones-balance parameter $m$ such that
$\operatorname{mtf}(m, \tilde{x}) = t$:

$$ \operatorname{mtf}(m, x) = \frac{(m-1)\,x}{(2m-1)\,x - m}. $$

Solving this equation for $m$ reveals an elegant property of the MTF: the solution is
expressed with the **same function**, arguments swapped,

$$ m = \operatorname{mtf}(t,\, \tilde{x}), $$

which the code exploits directly (`mtf(target, med)`) instead of inverting the equation by
hand. That MTF is then applied to the whole channel:

$$ s(x) = \operatorname{mtf}(m, x), $$

and the original and stretched versions are combined with a protection weight
$w(x) = 1 - x$ (a weighting purely based on pixel brightness, not an external mask):

$$ x' = x \cdot \big(1 - w(x)\big) + s(x)\cdot w(x) = x^2 + s(x)\,(1 - x). $$

As $x \to 1$ (highlights), $w(x) \to 0$ and $x' \to x$: the pixel is **almost unchanged**. As
$x \to 0$ (sky background), $w(x) \to 1$ and $x' \to s(x)$: the pixel receives the **full
stretch**. The iteration repeats this step until the channel's median reaches the target or
the `iterations` budget is exhausted.

## Parameters

- **`target_background`** — *real*, default `0.25`, range `0.01`–`0.9`. Target sky background
  level, expressed on the `[0,1]` scale of the stretched data. A higher value yields a visually
  brighter image with more contrast in the mid-tones.
- **`iterations`** — *int*, default `20`, range `1`–`200`. Number of stretch passes. More
  iterations bring the median closer to the target, with progressively smaller steps; beyond a
  certain count the gain becomes negligible.

## Tips & pitfalls

> **Warning** — the protection mask is based on **raw pixel value**, not on real star
> segmentation. Very bright nebulosity (that is not a star) will be protected the same way a
> star is — usually desirable, but it can be surprising on images with strong local contrast.

- A still very dark image (median near 0) often needs more iterations to converge; raise
  `iterations` rather than `target_background` if the result still looks flat.
- For finer control after this initial global stretch, chain `CurvesTransformation` or
  `HistogramTransformation` on the already "roughed-in" result.
- Unlike the STF (non-destructive preview), `MaskedStretch` **rewrites pixels**: work on a
  copy or check the history before chaining other linear-domain operations (which assume
  unstretched data).

## See also

- [HistogramTransformation](retina-doc://HistogramTransformation) — manual three-slider MTF
  stretch (shadows/midtones/highlights).
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — color-ratio-preserving stretch.
- [AutoHistogram](retina-doc://AutoHistogram) — automatic single-pass stretch.
- [AdaptiveStretch](retina-doc://AdaptiveStretch) — local-contrast-driven adaptive stretch.

## References

- PixInsight — *MaskedStretch* tool reference.
- Conejero, J. — *Midtones Transfer Function (MTF)*.
