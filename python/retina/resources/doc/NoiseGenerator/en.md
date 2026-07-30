---
id: NoiseGenerator
category: NoiseGeneration
title: Noise Generator
brief: Adds synthetic noise (gaussian, poisson or uniform) to the image, pixel by pixel.
keywords: [noise, gaussian, poisson, uniform, simulation, testing, denoising]
related: [SimplexNoise, NoiseReduction, FastNLMeansDenoise, WaveletDenoise]
icon: grain
references:
  - "PixInsight — NoiseGeneration tool reference."
  - "numpy.random.Generator — normal, poisson, uniform."
---

## Summary

`NoiseGenerator` adds **synthetic noise** to every pixel of the image, independently and
identically distributed (i.i.d.) per channel. Three models are available — **gaussian**
(additive, white), **poisson** (signal-dependent, shot-noise-like) and **uniform** (additive,
bounded) — the equivalent of PixInsight's `NoiseGeneration` tool. It is the functional inverse
of a denoiser: instead of removing noise, it injects some, in a controlled and reproducible way
via a seed.

## Use cases

- **Test a denoising pipeline** (`NoiseReduction`, `FastNLMeansDenoise`, `WaveletDenoise`…) on
  a known signal, comparing the noisy image against the clean original.
- **Simulate degraded frames** to validate a calibration/integration script without needing
  real noisy acquisitions.
- **Generate a background texture** (uniform or low-amplitude gaussian mode) for UI or
  rendering tests.
- **Study the robustness** of an algorithm (star detection, source extraction) against
  different noise levels and types.

## How it works

The process instantiates a numpy pseudo-random generator (`default_rng`) seeded by `seed`,
which makes the result **perfectly reproducible** for a given seed and image. Depending on
`type`:

- **`gaussian`** — a zero-mean normal draw with standard deviation `amount` is added to every
  pixel. This is **additive** noise, independent of the signal level — the standard model for
  electronic read noise.
- **`uniform`** — a uniform draw in `[-amount, amount]` is added to every pixel: also additive,
  but with a flat, bounded distribution rather than a gaussian bell.
- **`poisson`** — the image is first scaled by a factor derived from `amount` (the smaller
  `amount`, the larger the scale, hence the weaker the relative noise), a Poisson draw is
  performed on that scaled signal, and the result is divided back by the scale. Unlike the
  other two modes, this noise is **signal-dependent**: bright areas receive (in absolute terms)
  more noise than dark areas — the physical model of photon shot noise.

In every mode, the result is **clipped** to `[0, 1]` before being cast back to `float32`, to
stay within Retina's standard image representation range.

## Mathematics

Let $x$ be a pixel value in $[0,1]$ and $a$ = `amount`.

**Gaussian**: the added noise follows a zero-mean normal law with standard deviation $a$:

$$ x' = \operatorname{clip}(x + n,\; 0,\; 1), \qquad n \sim \mathcal{N}(0,\, a^2). $$

**Uniform**: the added noise is uniform over a symmetric interval of half-width $a$:

$$ x' = \operatorname{clip}(x + u,\; 0,\; 1), \qquad u \sim \mathcal{U}(-a,\, a). $$

**Poisson**: define a scale $\lambda_s = \max(a, 10^{-6}) \cdot 1000$, draw a Poisson count on
the rescaled signal, then renormalize:

$$ x' = \operatorname{clip}\!\left(\frac{P}{\lambda_s},\; 0,\; 1\right),
   \qquad P \sim \operatorname{Poisson}\big(\operatorname{clip}(x,0,1)\cdot \lambda_s\big). $$

The fundamental property of Poisson noise is that its variance equals its mean:
$\operatorname{Var}(P) = \lambda_s x$. After renormalizing by $\lambda_s$, the relative standard
deviation of the noise decreases as $1/\sqrt{\lambda_s x}$ — the stronger the signal $x$ (or the
larger $\lambda_s$, i.e. the larger `amount`), the lower the relative noise: this is the
expected behaviour of photon shot noise, where the signal-to-noise ratio grows with the number
of collected photons.

## Parameters

- **`type`** — *enum*, default `gaussian`, choices: `gaussian`, `poisson`, `uniform`.
  Statistical model of the added noise: additive gaussian (read noise), signal-dependent
  Poisson (photon shot noise), or additive uniform.
- **`amount`** — *real*, default `0.05`, range `0`–`1`. Noise amplitude. For `gaussian` and
  `uniform`, this is directly the standard deviation / half-width of the additive draw. For
  `poisson`, a smaller value produces *more* relative noise (smaller internal scale).
- **`seed`** — *int*, default `0`, range `0`–`2147483647`. Seed of the pseudo-random
  generator; fixes the draw so the result is reproducible across runs.

## Tips & pitfalls

> **Warning** — the `poisson` mode uses a different internal scale than the additive modes:
> `amount` does not represent a direct standard deviation there. Do not compare the three modes
> at the same `amount` expecting the same visual noise intensity.

- To reproduce a test exactly (bug reports, benchmarks), set `seed` to a nonzero value and
  record it: the default seed `0` always yields the same sequence.
- On an image already close to 0 or 1, the final clipping to `[0, 1]` locally biases the noise
  distribution (some draws are truncated) — worth knowing for quantitative analysis.
- For spatially correlated, textured noise (rather than pixel-by-pixel white noise), see
  [SimplexNoise](retina-doc://SimplexNoise).

## See also

- [SimplexNoise](retina-doc://SimplexNoise) — smooth fractal noise blended with the image.
- [NoiseReduction](retina-doc://NoiseReduction) — denoising to test against a noisy image.
- [FastNLMeansDenoise](retina-doc://FastNLMeansDenoise) — fast non-local-means denoising.
- [WaveletDenoise](retina-doc://WaveletDenoise) — wavelet-thresholding denoising.

## References

- PixInsight — *NoiseGeneration* tool reference.
- numpy.random.Generator — *normal*, *poisson*, *uniform*.
