---
id: HDRComposition
category: ImageIntegration
title: HDR Composition
brief: Merges exposures of increasing duration into a single high-dynamic-range image, discarding saturated pixels.
keywords: [HDR, high dynamic range, multiple exposures, saturation, star cores, scaling]
related: [GradientHDRComposition, Integration, FastIntegration, HDRMultiscaleTransform]
icon: stack
references:
  - "PixInsight — HDRComposition tool reference."
  - "Debevec, P. & Malik, J. — Recovering High Dynamic Range Radiance Maps from Photographs (1997)."
---

## Summary

`HDRComposition` combines a series of exposures of the **same field** with **increasing
durations** into a single image spanning a **wider dynamic range** than any single exposure
could capture. Short exposures supply unsaturated cores (stars, galactic nucleus, bright
nebular core) while long exposures reveal faint extensions; the process estimates the relative
exposure level of each frame and, at every pixel, excludes samples too close to saturation
before averaging what remains. It is a **global process**: it reads a list of files and creates
a new window, with no active view required.

## Use cases

- **Blown-out stellar or galactic cores**: combine a short exposure (core preserved) with a long
  one (background and extensions) to get an image free of clipped, plugged-up highlights.
- **High brightness-contrast nebulae** (M42/Orion being the classic case): the very bright
  central trapezium and the faint outer wisps cannot both fit within a single linear exposure.
- **A fast alternative** to gradient-domain HDR (`GradientHDRComposition`) when a simple
  saturation-weighted blend is sufficient.

## How it works

1. Each file in `frames` is loaded and its **global median** is computed; this median serves as
   a **proxy for relative exposure duration** (under a linear sensor response, the sky-background
   level grows roughly proportionally to exposure time).
2. The highest median — normally that of the longest exposure — becomes the **scale reference**.
   Every frame is rescaled to this common level: short exposures are amplified, the reference
   frame is left unchanged.
3. At each pixel, a frame only contributes to the average if its **raw** value (before rescaling)
   stays **below the `saturation` threshold**; pixels near or above the threshold are excluded
   for that frame, protecting core regions from saturation halos and artifacts.
4. The final pixel value is the **average of the rescaled, non-saturated frames**; if no frame is
   valid at a given location (all saturated), the process falls back to the last frame in the
   list. The result is finally **renormalized** by its maximum to stay within `[0, 1]`.

## Mathematics

Let $f_1, \dots, f_N$ be the $N$ exposures (indexed by increasing duration), and for each one the
global median $\tilde m_i = \operatorname{med}(f_i)$, used as a proxy for relative exposure
duration. The scale reference is the highest median:

$$ t_{\text{ref}} = \max_i \tilde m_i . $$

Each frame is brought to this common scale:

$$ \hat f_i(x) = f_i(x) \cdot \frac{t_{\text{ref}}}{\tilde m_i} . $$

A binary weight discards near-saturated pixels, evaluated on the **raw** (unscaled) value, with
$s$ = `saturation`:

$$ w_i(x) = \mathbb{1}\big[\, f_i(x) < s \,\big] . $$

The composite is the weighted average of the valid frames:

$$ C(x) = \begin{cases}
  \dfrac{\sum_{i=1}^{N} w_i(x)\, \hat f_i(x)}{\sum_{i=1}^{N} w_i(x)} & \text{if } \sum_i w_i(x) > 0 \\[1.2em]
  f_N(x) & \text{otherwise}
\end{cases} $$

and the final image is renormalized by its global maximum $M = \max_x C(x)$:

$$ H(x) = \frac{C(x)}{M} . $$

This is a simplified scheme (intended for images already in relative $[0,1]$ units, without an
explicit sensor response curve) compared to classical photographic HDR fusion methods (Debevec &
Malik): instead of inverting a radiometric response curve, it assumes a linear response and
estimates the scale factor from the global median.

## Parameters

- **`frames`** — *pathlist*, default `[]`. List of exposure files to combine, to be supplied in
  order of **increasing duration**. All exposures must share the same geometry (same framing,
  ideally registered if the instrument drifted between shots).
- **`saturation`** — *real*, default `0.9`, range `0.1`–`1.0`. Threshold (in normalized `[0,1]`
  units of the raw frame) above which a frame's pixel is considered saturated and excluded from
  the average for that frame.
- **`new_image_id`** — *str*, default `hdr`. Identifier of the image window created by the
  process.

## Tips & pitfalls

> **Warning** — exposures must share the **same framing**; the process performs no registration.
> Run `StarAlignment` beforehand if the telescope drifted between shots.

> **Note** — estimating relative duration from the **global median** assumes the sky background
> dominates the frame and grows linearly with exposure time. On a framing heavily dominated by a
> bright point source (comet, planet), this proxy can be misleading.

- A `saturation` value too close to 1.0 lets near-saturated pixels into the average, which can
  reintroduce mild highlight clipping. A value too low (< 0.5) can discard almost all of the
  shortest exposure over background regions, rendering it useless.
- If every exposure saturates at a given pixel, the output falls back to the last frame in the
  list (assumed to be the longest) — make sure `frames` is actually sorted by increasing
  duration.
- For a finer blend without a binary threshold or a linear-response assumption, see
  `GradientHDRComposition`, which works in the gradient domain and selects the best-exposed
  detail pixel by pixel.

## See also

- [GradientHDRComposition](retina-doc://GradientHDRComposition) — gradient-domain HDR
  composition, free of binary thresholds and seams.
- [Integration](retina-doc://Integration) — classic stacking with robust sigma rejection (same-
  duration exposures).
- [FastIntegration](retina-doc://FastIntegration) — fast rejection-free stacking, for a quick
  preview.
- [HDRMultiscaleTransform](retina-doc://HDRMultiscaleTransform) — multiscale dynamic-range
  compression on an already-composed image.

## References

- PixInsight — *HDRComposition* tool reference.
- Debevec, P. & Malik, J. — *Recovering High Dynamic Range Radiance Maps from Photographs* (1997).
