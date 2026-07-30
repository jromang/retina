---
id: SimplexNoise
category: NoiseGeneration
title: Simplex Noise
brief: Generates a smooth fractal noise field (sum of value-noise octaves) and blends it into the image.
keywords: [noise, simplex, fractal, octaves, texture, synthesis, value noise]
related: [NoiseGenerator, NoiseReduction, WaveletDenoise, FastNLMeansDenoise]
icon: grain
references:
  - "PixInsight — SimplexNoise tool reference."
  - "Perlin, K. — An Image Synthesizer, SIGGRAPH 1985 (gradient/value noise)."
  - "scipy.ndimage.zoom — spline interpolation for grid resampling."
---

## Summary

`SimplexNoise` synthesizes a **smooth fractal** noise field by summing several **octaves** of
value noise, each at twice the spatial frequency and half the amplitude of the previous one,
then blends this field into the image with a weight `amount`. The name refers to PixInsight's
simplex noise, but the Retina implementation is a **dependency-free approximation**: instead
of true simplex noise (Perlin's simplicial grid), it spline-interpolates a coarse random grid —
classic *value noise* — which yields a visually very close result (organic texture, no
preferred direction) for a minimal implementation cost.

## Use cases

- **Test a denoising pipeline**: inject controlled synthetic noise to compare `NoiseReduction`,
  `WaveletDenoise` or `FastNLMeansDenoise` on a known signal.
- **Simulate frames** to validate a calibration/integration script without hardware.
- **Generate background textures** (clouds, smoke, organic artifacts) for compositions or
  synthetic masks.
- **Slightly perturb** an overly smooth image (from a render or a very deep stack) to avoid
  banding during a subsequent stretch.

## How it works

1. For each octave $o$ (from `0` to `octaves - 1`), a coarse random grid of
   $\texttt{scale} \cdot 2^o$ cells per side is drawn (`numpy.random.default_rng(seed)`), then
   cubic-spline interpolated (`scipy.ndimage.zoom`, order 3) up to the full image size.
   Doubling the frequency at each octave progressively adds fine detail.
2. The octaves are summed with **decreasing amplitude** (factor `0.5` per octave, the classic
   fractal *persistence*), and the sum is normalized by the accumulated total weight.
3. The resulting field is **linearly renormalized** to `[0, 1]` (min → 0, max → 1) so the full
   dynamic range is used regardless of the octave count.
4. The noise field (replicated across all channels) is **blended** with the input image using
   the `amount` weight, and the result is clipped to `[0, 1]`.

> **Note** — this is not strictly *additive* noise: at `amount = 1.0`, the original image is
> **entirely replaced** by the noise field. For a discreet addition, use a small `amount`.

## Mathematics

Let $c_o$ be a coarse uniform random grid $\mathcal{U}(0,1)$ of resolution
$\texttt{scale}\cdot 2^{o}$, cubic-spline interpolated into a full-frame field $N_o(x,y)$.
The raw fractal field is the weighted sum over the $O$ = `octaves`:

$$ F(x,y) = \frac{1}{\sum_{o=0}^{O-1} 2^{-o}} \sum_{o=0}^{O-1} 2^{-o}\, N_o(x,y) $$

This is an **approximate 1/f noise**: each octave doubles the spatial frequency (finer detail)
while its amplitude is halved, the classic construction scheme for fractal noise (fBm /
multi-octave Perlin). The field is then renormalized over its observed range:

$$ \hat F(x,y) = \frac{F(x,y) - \min F}{\max F - \min F} $$

and linearly blended into the image $I$ with weight $a$ = `amount`:

$$ I'(x,y,c) = (1-a)\, I(x,y,c) + a\, \hat F(x,y), \qquad I' \leftarrow \operatorname{clip}(I', 0, 1) $$

with the same field $\hat F$ applied identically to every channel $c$ (achromatic noise).

## Parameters

- **`octaves`** — *int*, default `4`, range `1`–`8`. Number of summed noise layers. More
  octaves add fine detail (richer texture) at the cost of longer computation; beyond 6-7 the
  visual gain becomes marginal for most image sizes.
- **`scale`** — *int*, default `8`, range `2`–`256`. Number of cells of the base random grid
  (octave 0) per side. A low value yields large smooth blobs; a high value yields finer grain
  from the first octave already.
- **`amount`** — *real*, default `0.5`, range `0`–`1`. Blend weight between the original image
  (0) and the pure noise field (1). Controls the perceived intensity of the effect.
- **`seed`** — *int*, default `0`, range `0`–`2147483647`. Random generator seed; fixes the
  resulting texture for exact reproducibility between runs.

## Tips & pitfalls

> **Warning** — at high `amount`, the effect overwrites the image signal rather than adding to
> it: it is a **blend**, not additive noise scaled to the pixel range. To simulate realistic
> sensor noise (signal-dependent gaussian/poisson), prefer `NoiseGenerator`.

- Increasing `scale` while keeping `octaves` moderate yields a uniform fine grain, useful for
  simulating high-frequency noise without large-scale "organic" texture.
- The field is **achromatic** (identical across all channels): it does not simulate chrominance
  noise. For that, apply the process per channel via `ChannelExtraction` / `ChannelCombination`.
- Fix `seed` to compare two denoising settings on exactly the same injected noise.

## See also

- [NoiseGenerator](retina-doc://NoiseGenerator) — realistic gaussian/poisson/uniform (sensor) noise.
- [NoiseReduction](retina-doc://NoiseReduction) — denoising to test against synthetic noise.
- [WaveletDenoise](retina-doc://WaveletDenoise) — multiscale wavelet denoising.
- [FastNLMeansDenoise](retina-doc://FastNLMeansDenoise) — fast non-local means denoising.

## References

- PixInsight — *SimplexNoise* tool reference.
- Perlin, K. — *An Image Synthesizer*, SIGGRAPH 1985 (gradient/value noise).
- scipy.ndimage.zoom — spline interpolation for grid resampling.
