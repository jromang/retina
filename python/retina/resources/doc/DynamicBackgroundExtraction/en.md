---
id: DynamicBackgroundExtraction
category: BackgroundModelization
title: Dynamic Background Extraction
brief: Models and subtracts the sky background from manually placed sample points (PixInsight-style DBE).
keywords: [sky background, gradient, DBE, RBF, thin-plate spline, sample points, light pollution]
related: [BackgroundExtraction, RollingBallBackground, GradientCorrection, BackgroundNeutralization]
icon: layers-subtract
references:
  - "PixInsight — DynamicBackgroundExtraction tool reference."
  - "scipy.interpolate.RBFInterpolator — thin-plate spline interpolation."
  - "Duchon, J. (1977) — Splines minimizing rotation-invariant seminorms in Sobolev spaces (thin-plate splines)."
---

## Summary

`DynamicBackgroundExtraction` (DBE) models the sky background from a set of **sample points
placed by the user** at locations judged to be "pure background" (no star, no nebulosity). At
each point, a robust local statistic is measured, then a **smooth surface** is fitted through
those measurements — by RBF interpolation (thin-plate spline) or polynomial regression —
before being subtracted (or divided) from the image. This is the direct equivalent of
PixInsight's DBE: slower to set up than automatic grid-based extraction, but far more powerful
on complex or irregular gradients, because the user chooses exactly where the algorithm should
trust the background.

![Before — DynamicBackgroundExtraction](figures/before.webp)
![After — DynamicBackgroundExtraction](figures/after.webp)

*Before, and after an RBF model fitted through a coarse grid of samples on a real gradient.*

## Use cases

- **Complex gradients** that automatic grid-based extraction (`BackgroundExtraction`,
  `RollingBallBackground`) fails to follow well — asymmetric moon glow, directional light
  pollution, irregular residual vignetting.
- **Fields rich in extended nebulosity**, where an automatic grid risks mistaking faint signal
  for background: here the user deliberately avoids placing points on the nebula.
- **Fine, reproducible control**: points can be adjusted one at a time until the model captures
  no real signal, before freezing the treatment into a recipe.
- **Producing a standalone background model** (`subtract=False`) for inspection, or for reuse
  elsewhere (manual subtraction, `PixelMath`, comparison across sessions).

## How it works

1. **Robust local measurement.** For each point `(x, y)` in `samples`, a square patch of
   radius `sample_radius` is extracted around it, per channel. The patch median serves as the
   center, and a normalized MAD (`1.4826 × MAD`) serves as robust scale; pixels deviating by
   more than `tolerance` × that scale are rejected (typically star or nebulosity pixels
   contaminating the sample). The median of the surviving pixels gives the retained background
   value for that point and channel.
2. **Surface fitting.** The values measured at the surviving points (at least 3 required) act
   as nodes for a 2D interpolator/regressor, per channel:
   - `model = "rbf"`: interpolation via **thin-plate spline radial basis functions**
     (`scipy.interpolate.RBFInterpolator`), which passes (approximately, depending on
     `smoothing`) through each point while staying as smooth as possible elsewhere.
   - `model = "poly"`: 2D polynomial regression of degree `degree` by least squares, on
     coordinates normalized to `[0, 1]`.
3. **Application.** The resulting surface is evaluated over the full image grid, producing a
   background model `B(x, y)` per channel. If `subtract=True`, the output is
   `I − B + pedestal`; otherwise `B` itself is returned. The result is clipped to `[0, 1]`.

## Mathematics

**Robust per-point measurement.** Let $p$ be the patch of pixels around a sample point, for a
given channel. Its median $\tilde{p}$ and robust scale are computed as:

$$ \sigma_p = 1.4826 \cdot \operatorname{med}\big(|p - \tilde{p}|\big) $$

then only pixels compatible with the background are kept:

$$ K = \{\, v \in p : |v - \tilde{p}| < \tau\,\sigma_p \,\}, \qquad \tau = \texttt{tolerance} $$

with the retained value at the point being $\operatorname{med}(K)$. This rejection removes
stars and nebular structure that would otherwise bias the measurement upward.

**RBF interpolation (thin-plate spline).** Given $n$ control points
$\{(\mathbf{c}_i, v_i)\}_{i=1}^{n}$ with $\mathbf{c}_i \in \mathbb{R}^2$, the model is:

$$ B(\mathbf{x}) = \sum_{i=1}^{n} w_i\,\phi(\lVert \mathbf{x} - \mathbf{c}_i \rVert)
   + a_0 + a_1 x + a_2 y, \qquad \phi(r) = r^2 \log r $$

where the thin-plate kernel $\phi$ minimizes the rotation-invariant bending energy of the
interpolated surface — yielding a naturally smooth reconstruction between the points, free of
spurious oscillations. The weights $w_i$ and affine coefficients $a_k$ are found by solving a
linear system enforcing $B(\mathbf{c}_i) = v_i$ (exact interpolation when `smoothing = 0`) plus
the constraints $\sum_i w_i = \sum_i w_i \mathbf{c}_i = 0$. A `smoothing > 0` relaxes exact
interpolation by penalizing curvature, smoothing the model against noisy points.

**Polynomial regression.** With normalized coordinates $\hat{x} = x/(w-1)$,
$\hat{y} = y/(h-1)$, the coefficients $\beta_{ij}$ of

$$ B(\hat{x}, \hat{y}) = \sum_{i=0}^{d} \sum_{j=0}^{d-i} \beta_{ij}\, \hat{x}^{\,i}\, \hat{y}^{\,j},
   \qquad d = \texttt{degree} $$

are fitted by least squares, minimizing $\lVert A\boldsymbol\beta - \mathbf{v} \rVert_2^2$
(solved via `numpy.linalg.lstsq`) — a globally more rigid model than the RBF, suited to very
smooth, regular gradients.

**Final compositing.** If `subtract = True`:

$$ I'(x,y) = \operatorname{clip}\big(I(x,y) - B(x,y) + p,\; 0,\; 1\big), \qquad p = \texttt{pedestal} $$

otherwise $I' = \operatorname{clip}(B,\,0,\,1)$.

## Parameters

- **`samples`** — *pointlist*, default `[]`. List of `(x, y)` image-coordinate points at which
  to measure the background. At least 3 valid points (within the image frame) are required.
- **`sample_radius`** — *int*, default `15`, range `2`–`200`. Radius (in pixels) of the square
  patch used to measure the local background around each point.
- **`tolerance`** — *real*, default `3.0`, range `0.1`–`20.0`. Rejection threshold, in
  multiples of the normalized MAD, applied within the patch to discard stars and structure
  before measuring the background median.
- **`model`** — *enum*, default `rbf`, choices `rbf` / `poly`. Type of surface fitted to the
  measurements: thin-plate spline interpolation (`rbf`, flexible, follows local
  irregularities) or polynomial regression (`poly`, more rigid and global).
- **`degree`** — *int*, default `2`, range `1`–`6`. Degree of the 2D polynomial, used only when
  `model = "poly"`.
- **`smoothing`** — *real*, default `0.0`, range `0.0`–`100.0`. RBF smoothing factor (used only
  when `model = "rbf"`); `0` enforces exact interpolation at the points, a larger value allows
  deviation to produce a more regular surface.
- **`subtract`** — *bool*, default `True`. If true, subtracts the background model from the
  image; if false, returns the model itself (useful to check that it captures no real signal).
- **`pedestal`** — *real*, default `0.1`, range `0.0`–`1.0`. Additive offset applied after
  subtraction, to avoid pushing pixels below zero.

## Tips & pitfalls

> **Warning** — placing a point on a bright star or at the edge of a nebula locally biases the
> model: even with the patch's sigma rejection, a poorly placed point can pull the surface up
> or down over a wide area. Always inspect the model (`subtract=False`) before applying it.

> **Note** — with few points, a high polynomial `degree` or too small an RBF `smoothing` can
> overfit (the surface oscillates between points instead of staying smooth). Prefer more
> well-distributed points over a more complex model.

- Spread points across the **entire image**, including the corners: both RBF and polynomial
  fits extrapolate poorly outside the convex hull of the points.
- For a simple gradient (gentle vignetting, linear light-pollution slope), a low-degree
  `model = "poly"` (1 or 2) is often more stable than an RBF.
- For a quick automatic first pass before refining with DBE, `BackgroundExtraction` or
  `RollingBallBackground` provide a fast starting point.

## See also

- [BackgroundExtraction](retina-doc://BackgroundExtraction) — automatic grid-based extraction
  (ABE equivalent).
- [RollingBallBackground](retina-doc://RollingBallBackground) — rolling-ball background
  estimation.
- [GradientCorrection](retina-doc://GradientCorrection) — global gradient removal.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — colorimetric background
  neutralization, once flattened.

## References

- PixInsight — *DynamicBackgroundExtraction* tool reference.
- scipy.interpolate — *RBFInterpolator*, thin-plate spline interpolation.
- Duchon, J. (1977) — *Splines minimizing rotation-invariant seminorms in Sobolev spaces*
  (mathematical foundation of thin-plate splines).
