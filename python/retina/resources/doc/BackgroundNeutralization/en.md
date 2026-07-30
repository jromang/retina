---
id: BackgroundNeutralization
category: ColorCalibration
title: Background Neutralization
brief: Aligns the sky-background median across the three color channels to remove a color cast.
keywords: [sky background, color cast, color balance, sigma-clipping, robust median, color calibration]
related: [ColorCalibration, BackgroundExtraction, PhotometricColorCalibration, SCNR]
icon: color-swatch
references:
  - "PixInsight — BackgroundNeutralization tool reference."
  - "astropy.stats — sigma_clipped_stats (robust median via iterative sigma-clipping)."
---

## Summary

`BackgroundNeutralization` corrects a **color cast in the sky background** by realigning the
robust median of each color channel (R, G, B) onto the lowest of the three medians. A poorly
calibrated color image often shows a faint reddish, greenish, or bluish background (light
pollution, filters, sensor response); this process makes the background **hue-neutral** before
white balancing or stretching, without touching the rest of the dynamic range.

## Use cases

- **Remove a background color cast** before `ColorCalibration` or `PhotometricColorCalibration`,
  so those steps start from a neutral background.
- **Correct an RGB imbalance** caused by different exposure times or flats per filter.
- **Prepare an LRGB or OSC image** before stretching, when the sky background shows a visible
  tint on screen (often rust or yellow-green).
- Routine step in a color pipeline, right after `BackgroundExtraction`/gradient removal and
  before color calibration.

## How it works

The process only applies to images with **3 or more channels** (RGB); on mono data it is a
no-op. For each channel R, G, B:

1. Compute a **robust median** of the channel via iterative sigma-clipping (`astropy.stats.
   sigma_clipped_stats`, `sigma = 3.0`), which discards outliers — stars, hot pixels, bright
   nebulosity — to estimate only the **background level**.
2. The channel with the **lowest** median becomes the **reference** (`target`).
3. Every channel is **shifted** (constant, additive offset) so that its median reaches the
   `target` level: brighter channels are darkened accordingly, the reference channel is left
   unchanged.
4. The result is **clipped** to `[0, 1]`.

This is a **constant-offset** correction, not a multiplicative gain: it does not affect the
relative contrast within a channel, only its absolute background level.

## Mathematics

For each channel $c \in \{R, G, B\}$, let $\tilde{x}_c$ be the robust median obtained by
iterative $3\sigma$ sigma-clipping:

$$ \tilde{x}_c = \operatorname{sigma\_clipped\_median}(I_c,\; \sigma = 3) $$

The target is the lowest median of the three channels:

$$ t = \min(\tilde{x}_R,\, \tilde{x}_G,\, \tilde{x}_B) $$

and the correction applied to each channel is a simple shift:

$$ I_c'(x,y) = \operatorname{clip}\!\big(I_c(x,y) - (\tilde{x}_c - t),\; 0,\; 1\big) $$

After the transform, the three channels have (approximately) the **same background median** $t$:
the sky background becomes neutral gray, without altering the signal excess above that level.

## Parameters

This process has **no exposed parameters**: the estimator (3σ sigma-clipping) and the choice of
reference channel (lowest median) are fixed.

## Tips & pitfalls

> **Warning** — this process assumes the sky background is actually **the background**, i.e. the
> channel median is not polluted by extended nebulosity or a significant residual gradient. Run
> `BackgroundExtraction`/`GradientCorrection` **first** to flatten the background, otherwise the
> robust median can be biased by real signal.

- Only affects **color images (≥ 3 channels)**; has no effect on mono data.
- Does not replace a full colorimetric calibration (`ColorCalibration`,
  `PhotometricColorCalibration`): it neutralizes the **background**, not the color balance of
  the actual signal (stars, galaxies).
- Being a plain additive offset, it does not correct a spatially varying cast (a color
  gradient) — that is the role of `GradientCorrection` upstream.
- Always clipped to `[0, 1]`: on an image already close to saturation, a channel's negative
  shift can produce localized clipping; check the histogram afterwards.

## See also

- [ColorCalibration](retina-doc://ColorCalibration) — color balance via a white reference.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — flattens the background before neutralization.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — catalog-based color calibration.
- [SCNR](retina-doc://SCNR) — targeted reduction of a green cast (narrowband imaging).

## References

- PixInsight — *BackgroundNeutralization* tool reference.
- astropy.stats — *sigma_clipped_stats* (robust median via iterative sigma-clipping).
