---
id: Convolution
category: Convolution
title: Convolution
brief: Applies a smoothing or edge-enhancement filter (gaussian, box, laplacian) channel by channel.
keywords: [convolution, filter, gaussian, laplacian, smoothing, edge enhancement, scipy]
related: [GaussianConvolution, UnsharpMask, MorphologicalTransformation, NoiseReduction]
icon: focus-2
references:
  - "SciPy — scipy.ndimage: gaussian_filter, uniform_filter, gaussian_laplace."
  - "PixInsight — Convolution tool reference."
---

## Summary

`Convolution` is a generic spatial filtering operator offering three common kernels: **gaussian**
(gentle smoothing), **box** (uniform averaging, fast and crude smoothing) and **laplacian**
(edge enhancement). It complements `GaussianConvolution`, the native Rust operator dedicated to
pure gaussian blur: where that one targets performance on large images, `Convolution` builds
directly on `scipy.ndimage` to offer a wider variety of filters at the cost of a simpler,
single-threaded implementation.

## Use cases

- **Lightly smooth noise** before star analysis, masking, or source detection, when a fine
  gaussian blur is enough.
- **Fast, coarse blur** (`box` mode) to build a background mask or a low-frequency luminance map
  at minimal computational cost.
- **Enhance edges** (`laplacian` mode) to accentuate fine texture before a more elaborate
  sharpening step such as `UnsharpMask`.
- **Quickly compare common scipy filters** from the console without wiring a dedicated Rust
  pipeline for each variant.

## How it works

The process iterates over each color channel independently and applies the chosen filter via
`scipy.ndimage`:

1. **`gaussian`** — convolution with an isotropic 2D gaussian kernel parameterized by `radius`
   (used as the standard deviation σ): `ndimage.gaussian_filter(channel, sigma=radius)`. A soft,
   ripple-free blur that preferentially attenuates high frequencies (noise, fine detail).
2. **`box`** — a sliding average over a square window of side `round(radius)` pixels:
   `ndimage.uniform_filter(channel, size=...)`. Fast blur, but optically less "clean" (can
   introduce ringing artifacts around sharp edges).
3. **`laplacian`** — computes the laplacian of the image after gaussian smoothing with sigma
   `radius` (`gaussian_laplace`, a continuous approximation of the LoG filter) and **adds** it
   back to the original image. Since the laplacian is negative at the center of a transition and
   positive on its flanks, this addition locally boosts contrast at edges — a gentle sharpening
   effect, akin to a simplified unsharp mask.

In every case, the result is clipped to `[0, 1]` and cast back to `float32` before being written
back into the image.

## Mathematics

Let $I(x,y)$ be an image channel and $\sigma$ = `radius`.

**Gaussian filter.** The isotropic kernel is

$$ G_\sigma(x,y) = \frac{1}{2\pi\sigma^2}\, e^{-\frac{x^2+y^2}{2\sigma^2}}, \qquad
   I'(x,y) = (G_\sigma * I)(x,y). $$

**Box filter.** The kernel is a uniform window of side $n = \operatorname{round}(\sigma)$:

$$ I'(x,y) = \frac{1}{n^2} \sum_{i=-n/2}^{n/2}\sum_{j=-n/2}^{n/2} I(x+i,\,y+j). $$

**Laplacian filter (enhancement).** The laplacian of the gaussian-smoothed image is computed
first — the *Laplacian of Gaussian* (LoG) — then added back to the image:

$$ \operatorname{LoG}_\sigma(I) = \nabla^2 (G_\sigma * I)
   = \left(\frac{\partial^2}{\partial x^2} + \frac{\partial^2}{\partial y^2}\right) (G_\sigma * I), $$

$$ I'(x,y) = I(x,y) + \operatorname{LoG}_\sigma(I)(x,y). $$

The LoG kernel has the classic "Mexican hat" analytic form:

$$ \operatorname{LoG}_\sigma(x,y) = -\frac{1}{\pi\sigma^4}
   \left[1 - \frac{x^2+y^2}{2\sigma^2}\right] e^{-\frac{x^2+y^2}{2\sigma^2}}, $$

negative at the center of a transition and positive on its flanks: added to the image, it
slightly deepens the dark side of an edge and brightens its light side, increasing perceived
local contrast. In all three cases the output is finally clipped:
$I'' = \operatorname{clip}(I', 0, 1)$.

## Parameters

- **`filter`** — *enum*, default `gaussian`, choices `gaussian` / `box` / `laplacian`. Kernel
  type applied: gaussian smoothing, box averaging, or laplacian-of-gaussian edge enhancement.
- **`radius`** — *real*, default `2.0`, range `0.1`–`100.0`. Effective filter radius: kernel
  standard deviation σ for `gaussian` and `laplacian`, window side (rounded to an integer) for
  `box`.

## Tips & pitfalls

> **Warning** — in `laplacian` mode, too large a `radius` or a high-contrast image produces
> dark/light halos around bright stars and strong edges (over-sharpening effect). Start with
> small values (1–3 px) and inspect the result.

- In `box` mode, a `radius` below 0.5 rounds down to a 1-pixel window: the filter then has no
  effect.
- For pure gaussian blur on large images, prefer `GaussianConvolution`: its native Rust kernel
  releases the GIL and is significantly faster than `scipy.ndimage.gaussian_filter`.
- Laplacian enhancement also amplifies fine noise; consider a light denoise (`NoiseReduction`)
  before applying it to noisy images.

## See also

- [GaussianConvolution](retina-doc://GaussianConvolution) — native Rust gaussian blur, optimized
  for large images.
- [UnsharpMask](retina-doc://UnsharpMask) — more configurable sharpening (amount, threshold).
- [MorphologicalTransformation](retina-doc://MorphologicalTransformation) — non-linear filtering
  (erosion/dilation) for different structuring effects.
- [NoiseReduction](retina-doc://NoiseReduction) — denoise to run before an aggressive
  enhancement.

## References

- SciPy — *scipy.ndimage*: `gaussian_filter`, `uniform_filter`, `gaussian_laplace`.
- PixInsight — *Convolution* tool reference.
