---
id: DynamicPSF
category: ImageInspection
title: Dynamic PSF
brief: Measures the PSF (FWHM, eccentricity) over detected stars by fitting 2D Gaussians.
keywords: [PSF, FWHM, eccentricity, stars, DAOStarFinder, focus, optical quality]
related: [RadialProfileMeasurement, SubframeSelector, Deconvolution, StarMask]
icon: chart-dots-3
references:
  - "PixInsight — DynamicPSF tool reference."
  - "Stetson, P. B. (1987) — DAOPHOT: A Computer Program for Crowded-Field Stellar Photometry."
  - "photutils — DAOStarFinder and astropy.modeling.Gaussian2D."
---

## Summary

`DynamicPSF` measures the image's **Point Spread Function** by detecting stars and fitting a
**2D Gaussian** to the brightest of them. It derives two summary indicators: the **FWHM**
(full width at half maximum, in pixels), which quantifies star sharpness, and the
**eccentricity**, which quantifies star elongation. It is a **pure, non-destructive measurement**
process — like `Statistics` — that never touches pixel data: it fills `self.result` for
inspection from the console or a script.

## Use cases

- **Diagnose focus quality**: a high FWHM signals imperfect focus or strong atmospheric
  turbulence at the time of the exposure.
- **Detect tracking/guiding defects**: a high eccentricity betrays elongated stars (mount drift,
  mechanical backlash, poor polar alignment).
- **Parameterize a deconvolution**: the measured FWHM is a starting point for building the PSF
  kernel used by `Deconvolution`.
- **Select the best subframes** of a session before integration, by comparing FWHM and
  eccentricity frame by frame (complements `SubframeSelector`).

## How it works

The process runs in three steps:

1. **Robust background estimation** — `astropy.stats.sigma_clipped_stats` computes the median
   and standard deviation of the image (luminance = channel average if color) after iterative
   3σ rejection, so stars and outlier pixels do not bias the estimate.
2. **Source detection** — `photutils.detection.DAOStarFinder`, driven by `fwhm` (expected
   detection kernel size) and a threshold of `threshold_sigma × std` above the background, locates
   stellar peaks on the background-subtracted image. Sources are sorted by decreasing flux and the
   `max_stars` brightest are kept.
3. **Gaussian fitting** — for each retained star, a square ±6-pixel cutout around the centroid is
   extracted (stars too close to the border are skipped) and an
   `astropy.modeling.models.Gaussian2D` model is fitted by least squares (`LevMarLSQFitter`),
   with an initial standard deviation derived from the detection `fwhm`. The fit yields the
   Gaussian's standard deviations $\sigma_x, \sigma_y$, from which per-star FWHM and eccentricity
   are computed. The final result is the **median** of these values over all successfully fitted
   stars — robust to double stars, saturated stars, or failed fits, which are simply discarded.

## Mathematics

For each star, the fit produces an anisotropic 2D Gaussian:

$$ g(x, y) = A \exp\!\left[-\frac{(x - x_0)^2}{2\sigma_x^2} - \frac{(y - y_0)^2}{2\sigma_y^2}\right] $$

The **FWHM** of a 1D Gaussian with variance $\sigma^2$ is $2\sqrt{2\ln 2}\,\sigma \approx
2.3548\,\sigma$. For the fitted elliptical PSF, DynamicPSF combines the two axes through their
geometric mean:

$$ \mathrm{FWHM} = 2.3548 \sqrt{\sigma_x \, \sigma_y} $$

**Eccentricity** measures the flattening of the ellipse formed by the Gaussian's two axes. Writing
$a = \max(\sigma_x, \sigma_y)$ for the semi-major axis and $b = \min(\sigma_x, \sigma_y)$ for the
semi-minor axis:

$$ e = \sqrt{1 - \frac{b^2}{a^2}} $$

with $e = 0$ for a perfectly round star and $e \to 1$ for a strongly elongated one. The FWHM and
eccentricity values reported in `result` are the **medians** of the per-star values
$\{\mathrm{FWHM}_i\}$ and $\{e_i\}$ over the $n$ successfully fitted stars — a robust choice given
the handful of aberrant fits that are unavoidable on a real field.

## Parameters

- **`fwhm`** — *real*, default `3.0`, range `1.0`–`20.0`. Detection FWHM (pixels) passed to
  `DAOStarFinder`: the approximate expected stellar kernel size, and the initial standard
  deviation of the fitted Gaussian. Should match the actual sampling (too low underestimates it
  and misses broad stars; too high merges nearby stars).
- **`threshold_sigma`** — *real*, default `5.0`, range `1.0`–`50.0`. Detection threshold in
  multiples of the robust background standard deviation (σ). Lower values detect more faint
  sources, at the risk of picking up noise.
- **`max_stars`** — *int*, default `50`, range `1`–`500`. Maximum number of (brightest) stars the
  Gaussian is actually fitted to. A higher count stabilizes the median but slows the measurement.

## Tips & pitfalls

> **Warning** — on a noisy or under-sampled image, too low a `threshold_sigma` lets noise through
> that `DAOStarFinder` interprets as stars, biasing the median. Raise the threshold or lightly
> stretch the preview before measuring.

> **Note** — stars whose ±6 px cutout would extend past the image edge are silently skipped, as
> are those whose fit fails (double stars, saturated stars, or stars too close to a neighbor).
> `n_stars` in the result can therefore be lower than `max_stars`.

- If `n_stars` is 0, the field probably does not contain enough sharp stars above the threshold:
  lower `threshold_sigma` or check the exposure's focus.
- For a **per-star** inspection (full radial profile, not just aggregate FWHM/eccentricity), use
  `RadialProfileMeasurement`.
- A FWHM measured here is a good starting point for the Gaussian kernel radius in
  `Deconvolution`.

## See also

- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — radial profile and growth
  curve of the brightest star.
- [SubframeSelector](retina-doc://SubframeSelector) — subframe ranking/rejection by measured
  quality.
- [Deconvolution](retina-doc://Deconvolution) — sharpening restoration using the PSF as kernel.
- [StarMask](retina-doc://StarMask) — mask of detected stars.

## References

- PixInsight — *DynamicPSF* tool reference.
- Stetson, P. B. (1987) — *DAOPHOT: A Computer Program for Crowded-Field Stellar Photometry*.
- photutils — *DAOStarFinder* and *astropy.modeling.Gaussian2D*.
