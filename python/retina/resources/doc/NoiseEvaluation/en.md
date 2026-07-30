---
id: NoiseEvaluation
category: ImageInspection
title: Noise Evaluation
brief: Estimates per-channel noise dispersion, on the pixels that contain nothing else.
keywords: [noise, sigma, MRS, multiresolution support, k-sigma, wavelets, CFA, SNR]
related: [Statistics, NoiseReduction, SubframeSelector, MultiscaleLinearTransform]
icon: wave-sine
references:
  - "Starck, J.-L. & Murtagh, F. (1998) — Automatic noise estimation from the multiresolution support. PASP 110, 193."
  - "PixInsight — NoiseEvaluation script."
---

## Summary

On an image carrying stars, a nebula and a gradient, a robust standard deviation does not
measure noise: it measures **structure**. The question to answer is "what is the dispersion of
the pixels that contain *only* noise", and answering it requires telling the two apart first.

The difference is not marginal. On a synthetic field of eight thousand stars, with injected
noise of 0.0030:

| Method | Estimate |
|---|---|
| Global robust standard deviation (MAD × 1.4826) | 0.0223 |
| k-sigma clipping | 0.0066 |
| **Multiresolution support** | **0.0029** |

## Use cases

- **Compare two exposures**, two processings, two denoising settings — on a quantity that
  actually means something.
- **Set a threshold** expressed in σ (`MultiscaleLinearTransform`, deconvolution
  regularization): you still need to know what σ is.
- **Check a stack**: noise should fall as the square root of the frame count. If it plateaus,
  something is not adding up.

## How it works

### k-sigma

We work on the **first starlet layer** — the one where noise dominates — and iteratively clip
at `k_sigma` dispersions until the result stops moving. Robust, and it always returns something.

### Multiresolution support (MRS)

Any wavelet coefficient exceeding `k_sigma` times the **noise dispersion expected at its scale**
is marked significant; the marks are unioned, dilated by one pixel — a star spills beyond the
pixel that betrays it — and we measure only on what remains. The estimate feeds back into the
threshold until convergence.

The support covers only the **first two scales**, and that is a measurement rather than a
setting: beyond them, a dense field is significant *everywhere* at coarse scales, which is true
but has nothing to do with pixel-scale noise — and the estimate gives up. Below them, star wings
are still counted as background and noise comes out 8% high on two thousand stars, 55% on eight
thousand.

If the support leaves too few free pixels, the process **falls back to k-sigma** and says so:
`.result['method']` returns what *actually* ran, not what was asked for.

### Two factors people forget

The wavelet coefficients of Gaussian noise do not share the noise's dispersion: the B3-spline
convolution attenuates them by a known, tabulated factor (0.8907 at the first scale). And taking
the standard deviation of unclipped pixels only underestimates it, since the tails of the
Gaussian were cut — 1.3% at k = 3. Both corrections are applied; ignoring them leaves a constant
bias that nothing reveals as long as you only compare against yourself.

## CFA mode

On an **undebayered** image, the four sites of the matrix sit at different levels. A filter
mixing two neighbouring pixels then measures their difference — the mosaic, not the noise.
`cfa = True` estimates on the four sub-planes separately.

## Parameters

- **`method`** — *enum* `mrs` | `ksigma`, default `mrs`.
- **`k_sigma`** — *real*, default `3.0`, range `1`–`10`. Clipping and significance threshold.
- **`scales`** — *int*, default `4`, range `1`–`8`. Number of transform scales.
- **`cfa`** — *bool*, default `False`. Undebayered CFA image.

Read-only. `.result` carries, per channel, `sigma`, `fraction` (the share of pixels used),
`method`, `background` and `snr`.

## Tips & pitfalls

> **A low fraction is information.** If `fraction` drops to a few percent, there is barely any
> background left: the estimate still holds statistically (one percent of a megapixel is ten
> thousand pixels) but the margin is thinning.

- Noise is measured on **linear** data. After stretching, σ is no longer a constant of the
  image: it varies with level.
- An `snr` compares between frames of one series, not in the absolute: it depends on the
  background level, hence on light pollution and exposure time.

## See also

- [Statistics](retina-doc://Statistics) — ordinary statistics, including the MAD this process
  exists in order not to use.
- [NoiseReduction](retina-doc://NoiseReduction) — to act on what you have just measured.
- [SubframeSelector](retina-doc://SubframeSelector) — noise over a batch of frames.

## References

- Starck, J.-L. & Murtagh, F. (1998). *Automatic noise estimation from the multiresolution
  support*. PASP 110, 193.
- PixInsight — *NoiseEvaluation* script.
