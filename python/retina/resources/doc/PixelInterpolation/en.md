---
id: PixelInterpolation
category: CosmeticCorrection
title: Pixel Interpolation
brief: Fills NaN and dead pixels via interpolating Gaussian convolution (astropy interpolate_replace_nans).
keywords: [dead pixels, NaN, interpolation, Gaussian convolution, cosmetic, sensor]
related: [CosmeticCorrection, DefectMap, CosmicClip, Superbias]
icon: grid-dots
references:
  - "astropy.convolution — Gaussian2DKernel and interpolate_replace_nans."
  - "PixInsight — PixelMath / cosmetic correction, local neighborhood replacement."
---

## Summary

`PixelInterpolation` fills the holes in an image — pixels marked `NaN`, or pixels at 0/negative
if `mark_zeros` is enabled — using an **interpolating Gaussian convolution** that only draws on
valid neighbors (`astropy.convolution.interpolate_replace_nans`). Each missing pixel is replaced
by the Gaussian-weighted average of its healthy neighborhood; already-valid pixels are **never
altered**. It is the natural complement to `DefectMap`: where `DefectMap` repairs defects known
ahead of time (a supplied map), `PixelInterpolation` repairs holes already marked `NaN` in the
data (mosaic edges, rejection masks, saturated pixels set to NaN upstream, etc.).

![Before — PixelInterpolation](figures/before.webp)
![After — PixelInterpolation](figures/after.webp)

*Dead pixels, a dead patch and a dead column, and the frame after they are filled from their neighbours. The holes are injected — a frame that reaches the documentation has been calibrated and has none left.*

## Use cases

- **Fill holes** left by an upstream step that set certain pixels to `NaN` (integration
  rejection, cosmic-ray masking, out-of-field area from a reprojection/mosaic).
- **Remove known dead sensor pixels** that sit exactly at 0 or negative, by enabling
  `mark_zeros` — useful after a `Debayer` or a calibration step that left hard zeros.
- **Prepare an image for NaN-sensitive processing** (FFT, wavelets, statistics) that cannot
  tolerate any non-finite value.
- **Lightweight alternative to `DefectMap`** when no explicit defect map is available but the
  problem pixels are already identifiable by their value (NaN or zero).

## How it works

For each channel, independently:

1. If `mark_zeros` is enabled, every pixel `≤ 0` is first flipped to `NaN` — joining any pixels
   already marked dead.
2. If `NaN`s remain, `interpolate_replace_nans` convolves the channel with a 2D Gaussian kernel
   (`Gaussian2DKernel`, standard deviation `sigma`) in `nan_treatment='interpolate'` mode: the
   convolution ignores non-finite neighbors and **renormalizes the weights** over the valid ones.
3. Only pixels originally `NaN` are replaced by the result of this convolution; valid pixels
   keep their original value unchanged (no global smoothing of the image).
4. Any residual `NaN` (a hole wider than the kernel's support, no valid neighbor at all) is set
   to 0 as a safety net, and the result is clipped to `[0, 1]`.

## Mathematics

Let $I$ be an image channel and $p$ the position of a pixel flagged invalid. The isotropic
Gaussian kernel of radius $\sigma$ = `sigma` is, for an offset $(dx, dy)$:

$$ w(dx, dy) = \exp\!\left(-\frac{dx^2 + dy^2}{2\sigma^2}\right) $$

truncated to the kernel's finite support (a discrete centered window whose size depends on
$\sigma$). The interpolated value at the missing pixel is the **renormalized Gaussian-weighted
average** over the neighborhood $N(p)$ of valid pixels only:

$$ \hat{I}(p) = \frac{\displaystyle\sum_{q \in N(p),\; I(q) \text{ valid}} w(p - q)\, I(q)}
                    {\displaystyle\sum_{q \in N(p),\; I(q) \text{ valid}} w(p - q)} $$

Renormalizing by the sum of the *valid* weights (rather than the kernel's total weight) ensures
$\hat{I}(p)$ remains a true weighted average even when part of the neighborhood is itself
invalid — a necessary condition for closing holes several pixels wide, since successive
convolutions progressively fill in from already-recovered neighbors.

## Parameters

- **`sigma`** — *real*, default `2.0`, range `0.3`–`20.0`. Standard deviation (radius) of the
  Gaussian kernel used for interpolation. A small `sigma` interpolates tightly (locally
  faithful but may fail to bridge wide holes); a larger `sigma` smooths more and closes bigger
  holes, at the cost of more noticeable local blur around reconstructed pixels.
- **`mark_zeros`** — *bool*, default `False`. When enabled, treats every pixel `≤ 0` as dead: it
  is set to `NaN` before interpolation, exactly like a pre-existing `NaN`.

## Tips & pitfalls

> **Warning** — with `mark_zeros` enabled, a genuinely zero sky background (a perfectly
> subtracted image or a channel clipped to black) will also get interpolated. Only enable this
> option when hard zeros actually signal dead pixels, not a legitimate background level.

> **Note** — only pixels flagged invalid are ever modified: unlike a plain Gaussian blur, this
> operation does not degrade the sharpness of already-valid pixels.

- For very wide holes (dozens of pixels), increase `sigma`; otherwise residual `NaN`s will
  remain and simply be set to 0 as a fallback.
- If you have a defect map known ahead of time (mapped hot/cold pixels), prefer `DefectMap`,
  which uses a local median rather than a Gaussian average.
- For cosmic rays and transient streaks, `CosmicClip` is a better fit: it detects and corrects
  them without requiring the pixels to already be marked `NaN`.

## See also

- [DefectMap](retina-doc://DefectMap) — local-median replacement from a supplied defect map.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — automatic hot/cold pixel correction by deviation from the local median.
- [CosmicClip](retina-doc://CosmicClip) — cosmic-ray detection/rejection (LA Cosmic model).
- [Superbias](retina-doc://Superbias) — smooth master-bias modeling.

## References

- astropy.convolution — *Gaussian2DKernel* and *interpolate_replace_nans*.
- PixInsight — cosmetic correction and local neighborhood replacement (PixelMath).
