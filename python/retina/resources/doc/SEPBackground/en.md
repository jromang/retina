---
id: SEPBackground
category: BackgroundModelization
title: SEP Background
brief: Estimates and subtracts the sky background using sep (native Source-Extractor), very fast on large fields.
keywords: [sky background, SEP, SExtractor, gradient, background, ABE, light pollution]
related: [BackgroundExtraction, RollingBallBackground, SEPSourceExtraction, BackgroundNeutralization]
icon: layers-subtract
references:
  - "Bertin, E. & Arnouts, S. — SExtractor: Software for source extraction (1996)."
  - "Barbary, K. — sep: Python and C library for Source Extraction and Photometry."
---

## Summary

`SEPBackground` models the **sky background** (light-pollution gradients, residual vignetting,
moon glow) using `sep`, the Python/C port of SExtractor's background algorithm. It is the very
fast alternative to `BackgroundExtraction` (built on `photutils`): same star-resistant grid
principle, but a much lighter C implementation, particularly advantageous on large fields or in
batch processing.

## Use cases

- **Flatten a gradient** from light pollution or moonlight over a wide field under a tight time
  budget (batch processing, quick preview).
- **Correct residual vignetting** poorly calibrated by flats.
- **Extract the background model alone** (`subtract=False`) to inspect it before reusing it
  elsewhere (e.g. `PixelMath`) or to feed `SEPSourceExtraction`, which uses the same engine.

## How it works

The image is tiled into a grid of square boxes of side `box_size`. Within each box, `sep`
computes a background statistic **resistant to sources** after iterative sigma-clipping of bright
pixels (stars, artifacts). This per-box estimate is then smoothed by a sliding **median filter**
of size `filter_size` (expressed in neighboring boxes), which removes isolated local
overestimations caused by an extended object falling inside a single box. The smoothed grid is
finally **interpolated** (bicubic spline) into a continuous background surface at the image's full
resolution. The process handles each channel independently and, depending on `subtract`, either
subtracts that surface from the original image or returns it directly as output.

## Mathematics

On each grid box $b$, after iterative sigma-clipping of outlier pixels (stars), `sep` reuses
SExtractor's mode estimator, a combination of the robust median and mean:

$$ \mu_b = 2.5\,\operatorname{med}_b - 1.5\,\overline{x}_b $$

a valid approximation when the distribution of background pixels (excluding sources) stays close
to a lightly skewed Gaussian. The grid $\{\mu_b\}$ is then smoothed with a median filter of window
`filter_size` × `filter_size` (in box units):

$$ \tilde{\mu}_b = \operatorname{med}\big(\{\mu_{b'} : b' \in \mathcal{N}_\text{filter\_size}(b)\}\big), $$

then interpolated by bicubic spline to obtain the continuous background surface $B(x,y)$ at image
resolution. The output is:

$$ I'(x,y) = I(x,y) - B(x,y) \quad\text{if `subtract=True`,} \qquad I'(x,y) = B(x,y) \quad\text{otherwise,} $$

with the result finally clipped to $[0,1]$. No pedestal is added after subtraction: unlike
`BackgroundExtraction`, `SEPBackground` does not compensate for the negative values introduced by
the subtraction.

## Parameters

- **`box_size`** — *int*, default `64`, range `4`–`1024`. Side (in pixels) of the estimation
  boxes. A large value yields a very smooth background (good for broad gradients); a small value
  follows fine variations, at the risk of eating into extended nebulosity.
- **`filter_size`** — *int*, default `3`, range `1`–`15`. Size (in neighboring boxes) of the
  median filter applied to the background grid before interpolation. Increasing it smooths the
  background surface further and dampens artifacts from isolated boxes polluted by an extended
  source.
- **`subtract`** — *bool*, default `True`. If true, subtracts the background model from the image;
  otherwise, outputs the background model alone (useful for inspection or diagnostics).

## Tips & pitfalls

> **Warning** — as with any grid-based background estimator, too small a `box_size` models
> extended nebulosity as background and absorbs it along with the sky. On a diffuse object that
> covers a large part of the field, increase `box_size` or protect the area with a mask.

> **Note** — the subtraction adds back **no pedestal**: on an image already close to zero, it can
> produce negative values, which the process clips to 0. Check the resulting background before
> stretching.

- Output the model alone first (`subtract=False`) to visually confirm it holds no real signal
  before applying it for good.
- On a standard field (< 4000 px per side), `SEPBackground` and `BackgroundExtraction` give very
  similar results; prefer `SEPBackground` when speed matters (mosaics, batch runs).
- `SEPSourceExtraction` reuses the same `sep` engine for source detection: both processes share
  the same view of the sky background.

## See also

- [BackgroundExtraction](retina-doc://BackgroundExtraction) — photutils-based equivalent, with pedestal and choice of estimator.
- [RollingBallBackground](retina-doc://RollingBallBackground) — background modeling via rolling ball (morphological).
- [SEPSourceExtraction](retina-doc://SEPSourceExtraction) — source detection with the same `sep` engine.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — colorimetric background neutralization, a typical next step.

## References

- Bertin, E. & Arnouts, S. — *SExtractor: Software for source extraction* (1996).
- Barbary, K. — *sep*: Python and C library for Source Extraction and Photometry.
