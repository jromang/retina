---
id: AutoHistogram
category: IntensityTransformations
title: Auto Histogram
brief: Per-channel automatic stretch (robust median → target background), a destructive AutoSTF.
keywords: [auto-stretch, AutoSTF, MADN, median, MTF, stretch, linear]
related: [HistogramTransformation, MaskedStretch, ArcsinhStretch, BackgroundNeutralization]
icon: chart-bar
references:
  - "PixInsight — ScreenTransferFunction, AutoStretch button."
  - "Conejero, J. — Midtones Transfer Function (MTF)."
---

## Summary

`AutoHistogram` computes a per-channel automatic stretch — the same algorithm as the STF's
"AutoStretch" button in PixInsight — and **permanently applies it to the pixels**. It is the
"baked" (destructive) version of the auto-stretch: where the STF only changes the display
without touching the data, `AutoHistogram` rewrites the image into the view's history. It has
a single control, `target_background`, which sets the targeted sky-background brightness.

![Before — AutoHistogram](figures/before.webp)
![After — AutoHistogram](figures/after.webp)

*The linear frame as stored, and the same frame with its background driven to 0.25.*

## Use cases

- **Quickly rough out a linear image** fresh out of integration, to judge its quality (noise,
  gradients, stars) without manually dragging sliders.
- **Starting point** before refining with `HistogramTransformation` or `CurvesTransformation`.
- **Batch processing** (scripts, recipes) where a consistent, reproducible stretch is wanted
  across a series of images without manual intervention.
- Get a result **identical to what the STF preview shows**, but baked into the pixels for
  export or for chaining with other destructive operations.

## How it works

The process delegates the whole computation to `STF.auto_from_image` (the same function that
drives the STF's AutoStretch on display) — the single source of truth ensuring the baked
result matches the non-destructive preview exactly. For each channel:

1. Compute the **median** (robust center) and the **MADN** (normalized Median Absolute
   Deviation, ≈ a robust standard deviation, insensitive to stars and hot pixels).
2. Depending on whether the image is **dark** (median < 0.5, the classic linear case) or
   **bright** (median ≥ 0.5, an already-inverted image), place the black point or white point a
   few MADN away from the median (`shadows_clip = -2.8` internally), rejecting background noise
   without clipping real signal.
3. Solve for the MTF's midtones point so that the median, once remapped into the
   `[black point, white point]` range, lands exactly on `target_background` in the output.
4. The resulting STF is **applied to the pixels** (`stf.apply(data)`) — linear remap then MTF —
   producing the final result, written in place of the raw data.

## Mathematics

For a given channel, let $\tilde{x}$ be the median and
$\sigma = 1.4826 \cdot \operatorname{med}(|x_i - \tilde{x}|)$ the MADN. If $\tilde{x} < 0.5$
(linear image with a dark background):

$$ s = \operatorname{clip}(\tilde{x} + c\,\sigma,\; 0,\; 1), \qquad h = 1, $$

with $c = -2.8$ (background-noise rejection constant). The MTF's midtones point is chosen so
that the remapped median $x = \tilde{x} - s$ reaches exactly the target background $b$:

$$ m = \operatorname{mtf}(b,\, x) = \frac{(b-1)\,x}{(2b-1)\,x - b}. $$

(Symmetric case if $\tilde{x} \ge 0.5$, with $h$ tightened and the formula applied to
$h - \tilde{x}$, then $m \leftarrow 1 - m$.) The final per-pixel result is then the linear
remap followed by the MTF:

$$ x_n = \operatorname{clip}\!\left(\frac{x - s}{\,h - s\,},\, 0,\, 1\right), \qquad
   y = \operatorname{mtf}(m,\, x_n) = \frac{(m-1)\,x_n}{(2m-1)\,x_n - m}. $$

This function sends the median to `target_background` while keeping $0 \mapsto 0$ and
$1 \mapsto 1$: a gamma-like stretch driven by the image's own statistics rather than a manual
setting.

## Parameters

- **`target_background`** — *real*, default `0.25`, range `0.01`–`0.9`. Target background:
  the gray level (in `[0,1]`) the median should reach after stretching. A lower value (~0.15)
  gives a darker background and stronger contrast; a higher value (~0.35) lightens the
  background, useful on very noisy data where you want to lift faint signal.

## Tips & pitfalls

> **Warning** — this process is **destructive**: unlike the STF's auto-stretch (display only),
> `AutoHistogram` rewrites the pixels. Apply it on a copy, or verify the resulting stretch is
> satisfactory before chaining further irreversible operations.

> **Note** — the computation assumes **linear** data (background near zero). On an already
> stretched image, `AutoHistogram` can over-stretch or produce an inconsistent result; reserve
> it for the first stretch right after integration/calibration.

- Because the MADN is robust to outliers, a few saturated stars or hot pixels do not skew the
  black-point computation — unlike a plain standard deviation.
- For finer control (highlight protection, iterations), prefer `MaskedStretch`; to manually
  fine-tune the three sliders from this starting point, follow up with
  `HistogramTransformation`.

## See also

- [HistogramTransformation](retina-doc://HistogramTransformation) — manual control of the
  three sliders (shadows/midtones/highlights) using the same MTF model.
- [MaskedStretch](retina-doc://MaskedStretch) — iterative stretch protecting highlights.
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — color-preserving alternative without MTF.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — apply before stretching
  to neutralize a color cast in the sky background.

## References

- PixInsight — *ScreenTransferFunction*, *AutoStretch* button.
- Conejero, J. — *Midtones Transfer Function (MTF)*.
