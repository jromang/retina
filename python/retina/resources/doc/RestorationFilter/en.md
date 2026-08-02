---
id: RestorationFilter
category: Deconvolution
title: Restoration Filter (Wiener)
brief: Linear Wiener-filter deconvolution with a Gaussian PSF, fast and robust to noise.
keywords: [deconvolution, Wiener, PSF, restoration, regularization, Bayesian, sharpness]
related: [Deconvolution, GaussianConvolution, NoiseReduction, UnsharpMask]
icon: wand
references:
  - "scikit-image — skimage.restoration.wiener / unsupervised_wiener."
  - "Orieux, F., Giovannelli, J.-F., Rodet, T. (2010) — Bayesian estimation of regularization and PSF parameters for Wiener-Hunt deconvolution."
  - "Gonzalez, R. C., Woods, R. E. — Digital Image Processing, chap. Image Restoration (Wiener filter)."
---

## Summary

`RestorationFilter` restores an image blurred by a known Gaussian PSF using the **Wiener
filter**, a **linear, direct** deconvolution (no iterations) computed in the Fourier domain.
Unlike `Deconvolution` (Richardson-Lucy, iterative and non-linear), this filter is computed in
a single pass, making it noticeably faster at the cost of a simpler noise model. The `balance`
parameter arbitrates the sharpness/noise trade-off; the `unsupervised` mode estimates it
automatically through a Bayesian approach.

![Before — RestorationFilter](figures/before.webp)
![After — RestorationFilter](figures/after.webp)

*Before, and after a Wiener restoration — direct, non-iterative.*

## Use cases

- **Fast correction of focus blur or seeing turbulence** that can be modeled as Gaussian, on
  large images where Richardson-Lucy would be too slow.
- **Preprocessing before a heavier iterative treatment**: a first Wiener pass gives a decent
  result in a fraction of the time, useful to judge whether a deeper deconvolution is worthwhile.
- **When the noise level is not well known**: the `unsupervised` mode avoids manually tuning
  the regularization by trial and error.
- **Light restoration before `UnsharpMask`**, to avoid amplifying noise when sharpening an
  image that is still blurred.

## How it works

The process first builds a **Gaussian PSF kernel** sized from `psf_sigma` (radius
$\approx 3\sigma$, normalized to unit sum) — the same `_gaussian_psf` helper used by
`Deconvolution`. Each color channel is then processed independently:

1. Channel values are clipped to `[0, 1]`.
2. Depending on `mode`:
   - **`wiener`** — `skimage.restoration.wiener` applies the classic Wiener filter in the
     frequency domain, regularized by the `balance` parameter (bounds noise in the high
     frequencies where the PSF barely attenuates the signal).
   - **`unsupervised`** — `skimage.restoration.unsupervised_wiener` estimates the optimal
     regularization level and the noise level itself, via an iterative Bayesian algorithm
     (Gibbs sampling); no manual tuning is required.
3. The result is clipped back to `[0, 1]` across all channels.

Like `Deconvolution`, this process assumes an **isotropic, spatially invariant Gaussian PSF** —
a reasonable approximation for mild focus defects or average seeing, but not for a strongly
asymmetric real-world PSF (coma, sensor tilt).

## Mathematics

The degradation model is a noisy linear convolution:

$$ g(x,y) = (h * f)(x,y) + n(x,y), $$

where $f$ is the sought sharp image, $h$ the PSF (Gaussian kernel), and $n$ additive noise.
In the Fourier domain, with $H$, $F$, $N$, $G$ the respective transforms, the Wiener filter
estimates $F$ with the linear filter that minimizes the mean squared error:

$$ \hat{F}(u,v) = \left[\frac{H^{*}(u,v)}{\,|H(u,v)|^{2} + K(u,v)\,}\right] G(u,v), $$

where $H^{*}$ is the complex conjugate of $H$ and $K$ is the **regularization** term — strictly,
$K = S_n / S_f$ (the ratio of the noise and signal power spectral densities). In practice this
quantity is unknown: the `balance` parameter stands in for it, with a Tikhonov-style
regularization (by default based on a Laplacian operator rather than a flat constant) that
penalizes more heavily the high frequencies where the signal is most swamped by noise after
division by $|H|^2$ (near zero far from the PSF's center).

- **Small** `balance` ($\to 0$): $\hat{F} \to G/H$, a **pure inverse filter** — maximum
  sharpness but catastrophic noise amplification.
- **Large** `balance`: $K$ dominates over $|H|^2$, $\hat{F} \to (H^{*}/K)\,G$, correction fades
  out and the result approaches the original blurred image (smooth, stable behavior).

In `unsupervised` mode, $K$ (and the noise level) is not set by the user but **estimated jointly
with the image** through Bayesian inference, maximizing a posterior likelihood over a
hierarchical model (Orieux et al., 2010).

## Parameters

- **`psf_sigma`** — *real*, default `2.0`, range `0.1`–`20.0`. Standard deviation (in pixels) of
  the Gaussian PSF assumed to have degraded the image. Should match the actual blur spread: too
  small corrects nothing, too large over-corrects and introduces ringing artifacts.
- **`balance`** — *real*, default `0.1`, range `0.0001`–`10.0`. Regularization factor of the
  Wiener filter (`wiener` mode only). Small values → aggressive but noisy restoration; large
  values → gentle, stable restoration. Ignored in `unsupervised` mode.
- **`mode`** — *enum*, default `wiener`, choices `wiener` / `unsupervised`. `wiener` uses the
  manual `balance` regularization; `unsupervised` estimates it automatically through Bayesian
  inference (slower, but nothing to tune).

## Tips & pitfalls

> **Warning** — a Gaussian PSF is an approximation. On a strongly asymmetric real PSF (coma at
> the field edge, stars elongated by poor tracking), the isotropic Wiener filter will leave
> directional residuals; consider a per-region crop or a non-Gaussian PSF tool if available.

- Start with a high `balance` (soft result) and lower it progressively: amplified noise often
  appears abruptly below a certain threshold.
- The `unsupervised` mode is a good starting point to estimate an order of magnitude for
  `balance`, before switching back to `wiener` mode to fine-tune manually.
- Compared to `Deconvolution` (Richardson-Lucy), this filter does not enforce positivity by
  construction during the computation (hence the final clip) and may render fine, high-contrast
  detail less faithfully; reserve Richardson-Lucy when quality matters more than speed.
- Apply on a still-**linear** image (before histogram stretching): deconvolution assumes a
  linear degradation model, which a non-linear tone transformation would invalidate.

## See also

- [Deconvolution](retina-doc://Deconvolution) — iterative Richardson-Lucy deconvolution (slower, often more accurate).
- [GaussianConvolution](retina-doc://GaussianConvolution) — the inverse operation (Gaussian blurring), useful to test the PSF.
- [NoiseReduction](retina-doc://NoiseReduction) — denoising to pair with an aggressive restoration.
- [UnsharpMask](retina-doc://UnsharpMask) — local contrast sharpening, a lightweight alternative to deconvolution.

## References

- scikit-image — *skimage.restoration.wiener* / *unsupervised_wiener*.
- Orieux, F., Giovannelli, J.-F., Rodet, T. (2010) — *Bayesian estimation of regularization and PSF parameters for Wiener-Hunt deconvolution*.
- Gonzalez, R. C., Woods, R. E. — *Digital Image Processing*, chap. Image Restoration (Wiener filter).
