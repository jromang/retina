---
id: GradientCorrection
category: BackgroundModelization
title: Gradient Correction
brief: Removes a background gradient modeled by a robust polynomial surface (single global fit, no grid).
keywords: [gradient, sky background, light pollution, polynomial, vignetting, sigma-clip]
related: [BackgroundExtraction, MultiscaleGradientCorrection, DynamicBackgroundExtraction, RollingBallBackground]
icon: chart-line
references:
  - "PixInsight — DynamicBackgroundExtraction / AutomaticBackgroundExtractor tool reference."
  - "astropy.stats — sigma_clip for robust outlier rejection."
  - "numpy.linalg.lstsq — least-squares fitting."
---

## Summary

`GradientCorrection` models the sky background with a **single bivariate polynomial surface**,
fit to the whole image by least squares, and then subtracts it from the pixels (or displays it
as-is). Unlike `BackgroundExtraction`, which tiles the image into local boxes, this process
fits **one global polynomial** of adjustable degree — a fast, lightweight tool well suited to
smooth, global gradients (light pollution, residual vignetting, moon glow) rather than complex
local variations.

## Use cases

- **Remove a low-degree light-pollution gradient** (linear or gently curved) over a uniform
  field, without having to place manual sample points.
- **Correct residual vignetting** poorly calibrated by flats, using a degree-2 polynomial.
- **Get a quick, coarse fix** on the background before a finer pass with
  [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) or
  [BackgroundExtraction](retina-doc://BackgroundExtraction).
- **Inspect the model alone** (`subtract = False`) to verify it does not capture real
  astrophysical signal before applying it.

## How it works

For each color channel, independently:

1. Pixel coordinates `(x, y)` are normalized to `[0, 1]` across the image width and height,
   and all **monomials** $x^i y^j$ with $i + j \le$ `degree` are generated — this is the basis
   of the polynomial surface to be fitted.
2. A **robust rejection** step (`astropy.stats.sigma_clip`, 3σ threshold) discards pixel values
   too far from the global median: stars, prominent nebulosity, artifacts. Only the remaining
   background pixels take part in the fit.
3. The **polynomial coefficients** are estimated by least squares (`numpy.linalg.lstsq`) on the
   retained samples, and the surface is then **re-evaluated over every pixel** of the image
   (including those masked out in step 2) to obtain a continuous, complete model.
4. Depending on `subtract`, the result is either `image − model + pedestal` (flattened
   background, offset to stay positive), or the **model surface alone** — useful for inspecting
   it before committing the correction.

Fitting a single global surface (rather than a grid of local boxes) makes the process fast and
robust on small fields, but less able to track highly irregular gradients; see
[MultiscaleGradientCorrection](retina-doc://MultiscaleGradientCorrection) for a wavelet-based
approach that overcomes this limitation.

## Mathematics

Let $I(x,y)$ be an image channel of size $H \times W$. Coordinates are normalized:

$$ x_n = \frac{x}{W-1}, \qquad y_n = \frac{y}{H-1} \in [0,1]. $$

For a degree $d$ = `degree`, the retained monomial basis is

$$ \{\, x_n^{\,i}\, y_n^{\,j} \;:\; i,j \ge 0,\ i+j \le d \,\}, $$

of size $\binom{d+2}{2}$ (6 terms for $d=1$, 10 for $d=2$, and so on). The surface model is a
linear combination of that basis:

$$ S(x_n,y_n) = \sum_{i+j \le d} c_{ij}\; x_n^{\,i}\, y_n^{\,j}. $$

After robust outlier rejection (mask $M$ from a 3σ sigma-clip on intensities), the coefficients
$c_{ij}$ minimize the squared error over the retained pixels only:

$$ \hat{c} = \arg\min_{c} \sum_{(x,y) \in M} \big( I(x,y) - S(x_n,y_n;c) \big)^2, $$

solved by least squares (SVD decomposition via `numpy.linalg.lstsq`). The corrected image is
then:

$$ I'(x,y) = I(x,y) - S(x_n,y_n;\hat{c}) + p, \qquad p = \texttt{pedestal}, $$

with a final clip to $[0,1]$. With `subtract = False`, the output is $S(x_n,y_n;\hat{c})$
directly (no pedestal).

## Parameters

- **`degree`** — *int*, default `1`, range `1`–`5`. Degree of the bivariate polynomial fitted
  to the background. `1` = tilted plane (simple linear gradient); higher degrees capture
  increasingly complex curvature, at the risk of absorbing real signal if set too high.
- **`pedestal`** — *real*, default `0.1`, range `0`–`1`. Additive offset applied after
  subtraction, to avoid negative values being clipped to zero in faint background areas.
- **`subtract`** — *bool*, default `True`. If true, subtracts the model from the image
  (flattened background); if false, outputs the surface model itself, for inspection.

## Tips & pitfalls

> **Warning** — a high degree (4–5) on a field rich in extended nebulosity can mistake the
> diffuse signal for the gradient and absorb it into the model. Always start with `degree = 1`
> or `2` and check the model (`subtract = False`) before committing.

> **Note** — sigma-clip rejection protects against point-like stars and local artifacts, but
> not against extended low-contrast nebulosity: it can remain in the sample and slightly bias
> the fit.

- On a very irregular gradient (wall angle, local reflection), a global polynomial quickly hits
  a quality ceiling; prefer
  [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) (manual points) or
  [BackgroundExtraction](retina-doc://BackgroundExtraction) (local grid) instead.
- The process is **maskable**: apply a mask to explicitly protect a galaxy or extended nebula
  from the subtraction, on top of the automatic robust rejection.
- This process is not global: it applies to the active view (or a preview), not to a batch of
  files.

## See also

- [BackgroundExtraction](retina-doc://BackgroundExtraction) — local background modeling with a box grid (≈ABE).
- [MultiscaleGradientCorrection](retina-doc://MultiscaleGradientCorrection) — gradient removal via starlet wavelet residual.
- [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) — background modeled from manual sample points (≈DBE).
- [RollingBallBackground](retina-doc://RollingBallBackground) — background extraction via rolling-ball algorithm.

## References

- PixInsight — *DynamicBackgroundExtraction* / *AutomaticBackgroundExtractor* tool reference.
- astropy.stats — *sigma_clip* for robust outlier rejection.
- numpy.linalg.lstsq — least-squares fitting.
