---
id: WaveletDenoise
category: NoiseReduction
title: Wavelet Denoise
brief: Denoising via the stationary wavelet transform (SWT) with robust per-band soft thresholding.
keywords: [wavelets, SWT, soft thresholding, MAD, denoising, PyWavelets, multiscale]
related: [NonLocalMeansDenoise, TGVDenoise, MultiscaleLinearTransform, WaveletTransform]
icon: wave-sine
references:
  - "Donoho, D. L. & Johnstone, I. M. — Ideal spatial adaptation by wavelet shrinkage (1994)."
  - "Nason, G. P. & Silverman, B. W. — The stationary wavelet transform and some statistical applications (1995)."
  - "PyWavelets documentation — swt2 / iswt2 (stationary wavelet transform)."
---

## Summary

`WaveletDenoise` reduces noise by decomposing the image on a **stationary wavelet transform**
(SWT, also known as the undecimated à trous transform), then applying **soft thresholding** to
the detail coefficients of every band and scale before reconstruction. Unlike the classic
(decimated) DWT, the SWT is **translation-invariant**: it never subsamples, which eliminates the
block artifacts and checkerboard-like pseudo-structures typical of decimated wavelet denoising.
The threshold is derived automatically from the **robust noise level** (MAD) measured in each
band, with no manual per-scale tuning.

## Use cases

- **Denoise low-SNR images** (faint targets, short subs, light-polluted skies) while preserving
  fine structures better than plain spatial filters.
- **Clean up residual noise after stacking** without smoothing star edges or faint nebulosity
  filaments, thanks to adaptive per-band thresholding.
- **Alternative to `NonLocalMeansDenoise`** when the noise is roughly Gaussian/quasi-stationary
  and fine per-scale control via `level` is desired.
- **Pre-processing step** before an aggressive stretch (`HistogramTransformation`,
  `AdaptiveStretch`), which would otherwise amplify residual noise.

## How it works

For each color channel, independently:

1. **Mirror padding** of the image so its dimensions are multiples of `2**level`, a constraint
   imposed by the 2D SWT.
2. **SWT decomposition** (`pywt.swt2`) over `level` scales with wavelet `wavelet`, producing a
   low-frequency approximation and, at each scale, three detail bands (horizontal `cH`, vertical
   `cV`, diagonal `cD`).
3. For **each detail band**, robust estimation of the noise standard deviation via the band's
   **MAD** (Median Absolute Deviation), followed by **soft thresholding** of the coefficients at
   `threshold` times that estimate.
4. **Reconstruction** (`pywt.iswt2`) from the unchanged approximation and the thresholded
   details, then cropping back to the original size and clipping to `[0, 1]`.

The approximation (low frequencies, holding the sky background and broad structures) is never
thresholded: only the high-frequency noise carried by the details is attenuated.

## Mathematics

Let $c_{j,o}$ be the detail coefficients at scale $j \in \{1,\dots,\text{level}\}$ and
orientation $o \in \{H, V, D\}$ produced by the SWT. For each band, the robust noise standard
deviation is estimated via the **MAD**:

$$ \sigma_{j,o} = 1.4826 \cdot \operatorname{med}\big(\,|c_{j,o} - \operatorname{med}(c_{j,o})|\,\big) $$

The $1.4826$ factor makes this estimator consistent with the standard deviation of a normal
distribution. The threshold applied to the band is $t_{j,o} = k \cdot \sigma_{j,o}$, where
$k$ = `threshold`. Each coefficient then undergoes **soft thresholding**
(Donoho–Johnstone soft shrinkage):

$$ \hat{c} = \operatorname{sign}(c)\,\max\big(|c| - t_{j,o},\; 0\big) $$

Soft thresholding, unlike hard thresholding ($\hat c = c \cdot \mathbb{1}_{|c|>t}$), also
attenuates coefficients above the threshold, which yields a smoother reconstruction and avoids
visible discontinuities around the threshold. The reconstructed image is
$\hat{I} = \mathcal{W}^{-1}(\{a\},\{\hat{c}_{j,o}\})$, where $\mathcal{W}^{-1}$ is the inverse SWT
and $a$ the unmodified approximation.

## Parameters

- **`wavelet`** — *str*, default `db2`. Orthogonal wavelet family used by PyWavelets (e.g.
  `db2`, `sym4`, `coif1`). Daubechies wavelets (`dbN`) are a good general choice; symlets
  (`symN`) are more symmetric and distort edges less.
- **`level`** — *int*, default `3`, range `1`–`8`. Number of decomposition scales. More levels
  handle larger-scale noise structures but increase cost and the risk of smoothing away fine
  detail.
- **`threshold`** — *real*, default `3.0`, range `0`–`20`. Multiplicative factor `k` applied to
  each band's robust (MAD) spread to set the soft-thresholding level. Higher = more aggressive
  denoising but a greater risk of smoothing away faint structures.

## Tips & pitfalls

> **Warning** — too high a `threshold` flattens faint nebulosity filaments and fine galaxy
> texture, which share the same high-frequency content as noise. Check the result by zooming
> into low-signal areas, not just the sky background.

> **Note** — the image dimensions are automatically mirror-padded to satisfy the SWT's
> `2**level` constraint; the result is cropped back to the original size, no user action needed.

- Start with `level=3` and `threshold=3.0` (roughly a classic "3-sigma" threshold), then adjust:
  raise `threshold` on strong noise, lower it if fine detail degrades.
- On strongly non-Gaussian noise (chroma noise, compression artifacts), prefer
  `NonLocalMeansDenoise` or `TGVDenoise`, which handle those noise profiles better.
- Work preferably on still-linear or lightly stretched data: MAD-based thresholding assumes
  noise whose amplitude stays roughly homogeneous within each band.

## See also

- [NonLocalMeansDenoise](retina-doc://NonLocalMeansDenoise) — denoising via self-similar patches.
- [TGVDenoise](retina-doc://TGVDenoise) — edge-preserving variational denoising.
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — à trous starlet (a related multiscale approach).
- [WaveletTransform](retina-doc://WaveletTransform) — DWT decomposition/reconstruction with per-band gain.

## References

- Donoho, D. L. & Johnstone, I. M. — *Ideal spatial adaptation by wavelet shrinkage* (1994).
- Nason, G. P. & Silverman, B. W. — *The stationary wavelet transform and some statistical applications* (1995).
- PyWavelets documentation — *swt2* / *iswt2* (stationary wavelet transform).
