---
id: LocalNormalization
category: Calibration
title: Local Normalization
brief: Aligns a frame's background and scale onto a reference view before integration.
keywords: [normalization, integration, sky background, gradient, scale, stacking, rejection]
related: [Integration, StarAlignment, ImageCalibration, BackgroundExtraction]
icon: adjustments-horizontal
references:
  - "PixInsight — LocalNormalization / ImageIntegration (local normalization) tool reference."
  - "scipy.ndimage.gaussian_filter — low-pass Gaussian filtering."
---

## Summary

`LocalNormalization` fits a frame onto a common **reference view** before integration: it
equalizes both the **sky background** (the low-frequency component — gradients, residual
vignetting, light-pollution changes from one exposure to the next) and the overall **scale**
of the signal (transparency, exposure time, gain). Without this step, frames with slightly
different backgrounds or contrast produce gradient artifacts or a degraded outlier rejection
once stacked — `Integration` ends up comparing pixels that are no longer truly homogeneous
across frames.

## Use cases

- **Before `Integration`**, on a series of subs shot across different nights or sky
  conditions (variable transparency, changing moon glow), to bring every frame onto a common
  base and improve sigma rejection.
- **Fix a slight background mismatch** between subs caused by an imperfect flat or variable
  light pollution, without running a full per-frame `BackgroundExtraction`.
- **Even out a mosaic** or a multi-session set of subs before combining them, choosing the
  cleanest frame of the set as the reference.

## How it works

For each channel of the frame being normalized:

1. The **low-frequency background** of both the frame and the reference is estimated with a
   large-radius Gaussian blur (`scale`), which smooths out stars and noise, leaving only the
   slow background variation.
2. The **high-frequency component** (useful signal + noise) of each image is obtained by
   subtracting its own background: `hp = image - background`.
3. A **global multiplicative gain** is estimated as the ratio of the standard deviations of
   the frame's and the reference's high-frequency components — a simple, first-order-robust
   scale correction computed in a least-squares sense.
4. The output frame recombines the frame's high-frequency structure (rescaled by that gain)
   with the **reference's background**, which aligns both background level and contrast onto
   the common reference simultaneously.

If no reference is set, or it cannot be resolved (no such view), the process is a no-op: the
frame is returned unchanged.

> **Note** — the reference is resolved from its view identifier (`reference`) through the
> process execution context (`context.resolve_image_full`); it therefore must be a window
> already open in the application at execution time.

## Mathematics

Let $I$ be the frame to normalize and $R$ the reference, for a given channel. Each one's
low-frequency background is estimated by Gaussian convolution with parameter $\sigma$ =
`scale`:

$$ B_I = G_\sigma * I, \qquad B_R = G_\sigma * R. $$

The high-frequency components (signal + noise, background removed) are:

$$ H_I = I - B_I, \qquad H_R = R - B_R. $$

The scale gain is the ratio of the standard deviations of these components:

$$ g = \frac{\operatorname{std}(H_R)}{\operatorname{std}(H_I)}. $$

The normalized frame recombines $I$'s high-frequency structure, rescaled to $R$'s level, with
the reference's background:

$$ I'(x,y) = g \cdot H_I(x,y) + B_R(x,y), $$

after which the result is clipped to $[0,1]$. This additive (background) + multiplicative
(scale) model is a simplified version of PixInsight's local normalization model, which
estimates a $(\text{scale}, \text{background})$ pair locally over small tiles; here the gain
is **global** (a single scalar per channel) while the background stays **local** (a smoothed
2D map), which is enough to correct the bulk of inter-frame drift while staying fast and
purely numpy/scipy.

## Parameters

- **`reference`** — *str*, default `""`. Identifier of the reference view to align background
  and scale onto. Empty or unresolvable view → the frame is returned unchanged (no-op).
- **`scale`** — *real*, default `128.0`, range `4`–`1024`. Standard deviation $\sigma$ (in
  pixels) of the Gaussian blur used to estimate the low-frequency background. Larger values
  give a very smooth background (only broad gradients captured); smaller values follow finer
  variations, at the risk of absorbing extended signal (nebulosity).

## Tips & pitfalls

> **Warning** — too small a `scale` treats extended nebulosity as background and partially
> dilutes it in every normalized frame. Pick a value clearly larger than the structures of
> interest.

- Choose the cleanest, best-exposed frame of the set as `reference` (little gradient, stable
  transparency), not necessarily the first frame of the sequence.
- Run `LocalNormalization` on frames that are already **calibrated** (`ImageCalibration`) and
  **aligned** (`StarAlignment`): the background/scale correction only makes sense if the
  pixels being compared cover the same patch of sky.
- The estimated gain is **global per channel**, not local: it does not correct a contrast
  gradient that varies across the field. For a complex background gradient, a per-frame
  `BackgroundExtraction` upstream remains complementary.

## See also

- [Integration](retina-doc://Integration) — next step: stacking with robust rejection.
- [StarAlignment](retina-doc://StarAlignment) — prior geometric registration of the frames.
- [ImageCalibration](retina-doc://ImageCalibration) — upstream bias/dark/flat calibration.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — full per-frame background modeling.

## References

- PixInsight — *LocalNormalization* / *ImageIntegration* (local normalization) tool reference.
- scipy.ndimage — *gaussian_filter*, low-pass Gaussian filtering.
