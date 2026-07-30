---
id: GalaxyModel
category: MultiscaleProcessing
title: Galaxy Model (isophotes)
brief: Fits concentric isophotal ellipses to a galaxy and subtracts the smooth model to reveal overlaid structure.
keywords: [galaxy, isophotes, ellipse, photutils, spiral arms, smooth model, residual]
related: [RadialProfileMeasurement, BackgroundExtraction, LarsonSekanina, MultiscaleMedianTransform]
icon: atom
references:
  - "photutils.isophote — Ellipse, EllipseGeometry, build_ellipse_model."
  - "Jedrzejewski, R. (1987), MNRAS 226, 747 — Adaptive iterative isophote-fitting method (IRAF ELLIPSE)."
---

## Summary

`GalaxyModel` fits a family of **concentric isophotal ellipses** to the smooth body of a galaxy
(via `photutils.isophote.Ellipse`, a descendant of IRAF's ELLIPSE algorithm), then reconstructs a
**smooth light-distribution model** from those ellipses. Subtracted from the original image, this
model exposes everything that departs from elliptical symmetry — spiral arms, bars, overlaid
globular clusters, tidal tails, dust — by removing the dominant disk/bulge brightness gradient
that would otherwise bury these fainter details.

## Use cases

- **Reveal spiral arms and fine structure** in a galaxy whose smooth body crushes the contrast of
  finer detail, by working on the residual (image − model).
- **Isolate globular clusters or HII regions** superimposed on the disk, easier to spot and
  process (sharpening, coloring) once the galactic background is flattened.
- **Detect tidal tails or irregularities** betraying an interaction or merger, invisible under the
  bright halo of the main body.
- **Export the model alone** (`subtract=False`) to inspect it, compare it to a radial profile, or
  use it as a symmetry reference.

## How it works

The process treats each channel independently:

1. The starting center `(x0, y0)` is fixed (or taken at the image midpoint if `-1`), and an
   initial ellipse geometry is built from the starting semi-major axis `sma0`, ellipticity `eps`
   and a zero position angle.
2. `Ellipse.fit_image()` grows/shrinks this geometry step by step (geometric step) and, at each
   radius, **adjusts** the center, ellipticity and position angle by minimizing the low-order
   Fourier harmonics of the intensity sampled along the ellipse — the iterative Jedrzejewski
   (1987) method ported from IRAF ELLIPSE. The result is a list of fitted isophotes (`isolist`),
   one per radius.
3. `build_ellipse_model()` interpolates these isophotes to reconstruct a **full-resolution smooth
   image**: each pixel is assigned the intensity of the isophote passing through its radial
   position.
4. Depending on `subtract`, the output is the **residual** (channel − model) or the **model**
   itself; the result is clipped back into `[0, 1]`.

If the fit converges on **no** isophote at all for a channel (galaxy too faint, badly placed
center, saturated image…), that channel is returned **unchanged**, with no error — the process
can therefore fail silently and partially.

## Mathematics

For an ellipse centered at $(x_0, y_0)$, with semi-major axis $a$ (the current `sma`), ellipticity
$\varepsilon = 1 - b/a$ and position angle $\theta_0$, the intensity is sampled along the
elliptical contour as a function of the eccentric angle $\theta$. It is decomposed into a
truncated Fourier series:

$$ I(\theta) \approx I_0 + A_1 \sin\theta + B_1 \cos\theta + A_2 \sin 2\theta + B_2 \cos 2\theta. $$

$I_0$ is the **mean isophote intensity** (the level retained for that value of $a$); the harmonics
$A_1, B_1$ reflect **mis-centering**, and $A_2, B_2$ **incorrect ellipticity or position angle**.
At each iteration, the algorithm updates $(x_0, y_0, \varepsilon, \theta_0)$ in the direction that
reduces the amplitude of these harmonics, until convergence or failure (too noisy, image edge,
non-closed isophote).

The reconstructed model $M(x,y)$ interpolates $I_0(a)$ between successive fitted radii. The output
is then, per channel:

$$ I_{\text{out}}(x,y) = \operatorname{clip}\!\big(I(x,y) - M(x,y),\; 0,\; 1\big) \quad
   \text{(if `subtract=True`)}, \qquad
   I_{\text{out}}(x,y) = M(x,y) \quad \text{(otherwise)}. $$

## Parameters

- **`x0`** — *int*, default `-1`, range `-1`–`1000000`. Starting X center in pixels; `-1` = image
  midpoint.
- **`y0`** — *int*, default `-1`, range `-1`–`1000000`. Starting Y center in pixels; `-1` = image
  midpoint.
- **`sma0`** — *real*, default `10.0`, range `1.0`–`1000.0`. Semi-major axis (pixels) of the first
  fitted isophote; starting point for geometric growth both inward and outward.
- **`eps`** — *real*, default `0.2`, range `0.0`–`0.95`. Initial ellipticity $1 - b/a$ of the
  starting geometry (0 = circle, near 1 = very flattened ellipse).
- **`subtract`** — *bool*, default `True`. If true, output = image − model (residual). If false,
  output = the smooth model itself.

## Tips & pitfalls

> **Warning** — the fit runs **per channel**, independently. On a color image, differing
> convergence across channels (or one channel silently falling back to the original on failure)
> produces **color fringing** in the residual. For a clean result, it is often better to run the
> process on a grayscale or luminance version first, then recombine.

> **Note** — the process is **not maskable** (`is_maskable = False`). To restrict work to the
> galaxy, isolate it first in a `Preview` or `Crop` before running the process.

- Pick `sma0` on a well-defined isophote of the disk, away from the nucleus (often saturated or
  very peaked) and away from bright foreground stars.
- An initial `eps` too far from the galaxy's true ellipticity can prevent convergence at the very
  first radii; a rough by-eye estimate is usually enough.
- Silent failure (channel unchanged) is common on faint or low-contrast galaxies: always check the
  result by first outputting the model alone (`subtract=False`).
- On strongly asymmetric galaxies (interaction, merger), the elliptical-isophote assumption is
  strained: the order-2 harmonics will not converge well, which is itself revealing but limits the
  quality of the smooth model.

## See also

- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — radial profile measurement,
  complementary to isophote analysis.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — the same smooth-model-subtraction
  logic, applied to the sky background rather than a galaxy.
- [LarsonSekanina](retina-doc://LarsonSekanina) — another enhancement technique via subtraction of
  a smooth radial/rotational model, for comets.
- [MultiscaleMedianTransform](retina-doc://MultiscaleMedianTransform) — structure separation
  across scales, an alternative way to reveal overlaid detail.

## References

- photutils.isophote — *Ellipse*, *EllipseGeometry*, *build_ellipse_model*.
- Jedrzejewski, R. (1987), *MNRAS* 226, 747 — adaptive iterative isophote-fitting method (IRAF
  ELLIPSE).
