---
id: ColorCalibration
category: ColorCalibration
title: Color Calibration
brief: White balance from reference regions (white + background), with robust background neutralization.
keywords: [white balance, gray-world, background neutralization, color reference, preview, colorimetric calibration]
related: [PhotometricColorCalibration, SpectrophotometricColorCalibration, BackgroundNeutralization, LinearFit]
icon: palette
references:
  - "PixInsight — ColorCalibration tool reference."
  - "Buchsbaum, G. — A spatial processor model for object colour perception, 1980 (gray-world hypothesis)."
  - "astropy.stats — sigma_clipped_stats (robust median estimator)."
---

## Summary

`ColorCalibration` corrects an RGB image's color cast in two steps: a **white balance** that
equalizes per-channel gains over a region assumed to be neutral, followed by a **sky background
neutralization** that aligns the channel medians in a background region to remove any residual
tint in the black. It is the lightweight counterpart to PixInsight's `ColorCalibration` tool
(as opposed to its photometric variant, which relies on a star catalog).

## Use cases

- **Correct a color cast** caused by light pollution, a filter, or an unbalanced sensor, without
  photometric reference measurements.
- **Neutralize the sky background** before stretching, to avoid a greenish or magenta background
  that would otherwise be amplified by `HistogramTransformation` or `CurvesTransformation`.
- **Quick calibration** in gray-world mode when no obvious reference region is available (rich
  field, no identifiable neutral galaxy).
- **Refine on a chosen region** (a preview placed on a known white star, or on a background
  patch free of signal) when the global gray-world assumption fails (field dominated by a red
  nebula, for instance).

## How it works

The process leaves non-RGB images unchanged (fewer than 3 channels, returned as-is) and runs
two independent passes:

1. **White balance.** The region named by `white_reference` (a named preview) acts as the
   "neutral" reference; if the parameter is empty, the reference is the **entire image**
   (*gray-world* hypothesis: a natural scene averages to gray). The mean of each channel is
   computed over this region, then a per-channel gain brings the three means to a common value.
   This gain is applied to the **whole image**, not just the reference region.
2. **Background neutralization.** The region named by `background_reference` (another named
   preview) acts as the background reference; if the parameter is empty, the **gain-corrected
   image** (the output of step 1) is used instead. For each channel, a robust median is
   estimated via sigma-clipping (`astropy.stats.sigma_clipped_stats`, `sigma=3`) to ignore
   stars or faint signal that might fall inside it. The channel with the lowest median becomes
   the floor; the other channels are shifted down to match it, and no channel is ever shifted
   up. The result is finally clipped to `[0, 1]`.

> **Note** — when `background_reference` is explicitly set, its median is computed on the
> **original** pixels of the named view/preview, not on the image after the step-1 gain has
> been applied. This only matters if the background preview overlaps the gained image in a
> non-trivial way (normal usage: distinct previews → no impact).

## Mathematics

Let $I(x,y,c)$ be the input image for $c \in \{R,G,B\}$, and $W$ the white reference region
(the entire image if `white_reference` is empty). The per-channel mean is:

$$ \mu_c^{W} = \max\!\big(\operatorname{mean}(W_c),\ 10^{-6}\big) $$

and the common **target**, the mean of the three means:

$$ t = \frac{1}{3}\sum_{c} \mu_c^{W}. $$

The gain applied to each channel equalizes the white region's means onto this target:

$$ g_c = \frac{t}{\mu_c^{W}}, \qquad I'(x,y,c) = I(x,y,c)\cdot g_c. $$

For background neutralization, let $B$ be the background region (the gained image $I'$ if
`background_reference` is empty, otherwise the original pixels of the named preview). A robust
per-channel median is estimated via $3\sigma$ clipping:

$$ m_c = \operatorname{med}_{3\sigma}(B_c), \qquad f = \min_c m_c. $$

The final shift subtracts each channel's excess above the floor $f$:

$$ I''(x,y,c) = \operatorname{clip}\!\big(I'(x,y,c) - (m_c - f),\ 0,\ 1\big). $$

The channel with the lowest background median is therefore never altered at this step; the
others are pulled down until all three background medians coincide.

## Parameters

- **`white_reference`** — *str*, default `''`. Identifier of a preview used as the "white"
  reference for white balance. Empty → gray-world (mean over the whole image).
- **`background_reference`** — *str*, default `''`. Identifier of a preview used as the
  background reference for neutralization. Empty → uses the whole (gain-corrected) image.

## Tips & pitfalls

> **Warning** — gray-world white balance assumes the field's average color is neutral. Over a
> field dominated by a large red nebula or a chromatically strong galaxy, that assumption
> fails: place a preview over a neutral region (a white star, a wide sky patch) via
> `white_reference` instead of relying on the default gray-world mode.

- Always place the background preview (`background_reference`) over an area **free of signal**
  (no stars, no faint nebulosity): the robust median tolerates a few outliers, but not a region
  mostly occupied by real signal.
- This process operates on data that is **already calibrated and linear** (after
  `ImageCalibration` and ideally after `BackgroundExtraction`); running it on an already
  stretched image shifts tones in a non-physical way.
- For a calibration anchored in real spectrophotometric measurements rather than statistical
  assumptions, see `PhotometricColorCalibration` or `SpectrophotometricColorCalibration`.
- Mono images or images with fewer than 3 channels pass through unmodified.

## See also

- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — calibration anchored in a photometric catalog.
- [SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration) — calibration from reference spectra.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — background neutralization alone, without white balance.
- [LinearFit](retina-doc://LinearFit) — linear alignment of channels/frames onto a reference.

## References

- PixInsight — *ColorCalibration* tool reference.
- Buchsbaum, G. — *A spatial processor model for object colour perception*, 1980 (gray-world hypothesis).
- astropy.stats — *sigma_clipped_stats* (robust median estimator).
