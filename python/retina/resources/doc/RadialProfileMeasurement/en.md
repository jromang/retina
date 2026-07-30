---
id: RadialProfileMeasurement
category: ImageInspection
title: Radial Profile Measurement
brief: "Radial profile and curve of growth of the brightest star, with fitted FWHM (photutils)."
keywords: [FWHM, radial profile, curve of growth, focusing, collimation, photutils, star]
related: [DynamicPSF, Statistics, SubframeSelector, StarMask]
icon: chart-arcs
references:
  - "photutils.profiles — RadialProfile and CurveOfGrowth."
  - "PixInsight — PSF / star profile inspection tools."
---

## Summary

`RadialProfileMeasurement` measures how a star's light is distributed around its center: it
automatically locates the brightest pixel in the image, then samples two curves around that
peak — the **radial profile** (azimuthally-averaged intensity per concentric annulus) and the
**curve of growth** (cumulative flux inside circular apertures of increasing radius). A Gaussian
is fitted to the radial profile to extract the **FWHM** in pixels. This is a **pure measurement**
process, read-only: it never modifies pixels, it simply fills `.result` with the numeric data.

## Use cases

- **Live focusing check** on a bright star: track the fitted FWHM to refine focuser position
  down to its minimum.
- **Collimation/optics diagnosis**: an asymmetric radial profile, or a curve of growth that
  doesn't clearly plateau, points to an optical aberration or a collimation defect.
- **Visually compare several frames** by plotting their radial profiles side by side (via
  `.result["radius"]`/`.result["profile"]`) to spot tracking blur or seeing degradation.
- **Estimate the optimal aperture radius** for aperture photometry by reading off the curve of
  growth the radius where cumulative flux flattens out.

## How it works

1. The image is reduced to a luminance map (channel average if the image is color).
2. The maximum-value pixel of that luminance map is taken as the **star center** — no source
   detection happens beforehand: the process assumes the brightest star in the image (or in the
   preview passed as input) clearly dominates the field.
3. Concentric annuli (photutils' `RadialProfile`), with edges from 0 to `max_radius` in 1-pixel
   steps, give the azimuthally-averaged intensity at each radius.
4. Nested circular apertures of increasing radius (photutils' `CurveOfGrowth`, same radii minus
   the zero radius) give the total cumulative flux up to each radius.
5. A 1D Gaussian is fitted to the radial profile to derive the FWHM
   (`RadialProfile.gaussian_fwhm`); the fit fails silently (FWHM set to `None`) if the profile is
   degenerate (flat background, saturated star, non-finite data).

## Mathematics

Let $I(x,y)$ be the luminance map and $(x_c, y_c)$ the maximum-value pixel. For a pixel at
distance $r = \sqrt{(x-x_c)^2 + (y-y_c)^2}$, the **radial profile** discretized into annuli
$[r_k, r_{k+1}[$ is the intensity averaged with the geometric overlap weight of pixels in the
annulus:

$$ P(r_k) = \frac{\sum_{(x,y) \in \text{annulus}_k} w_{x,y}\, I(x,y)}{\sum_{(x,y) \in \text{annulus}_k} w_{x,y}} $$

where $w_{x,y} \in [0,1]$ is the fraction of the pixel's area covered by the annulus (`exact`
method). The **curve of growth** is the flux integrated inside the disk of radius $r_k$:

$$ C(r_k) = \sum_{(x,y) \in \text{disk}(r_k)} w_{x,y}\, I(x,y). $$

The FWHM is obtained by fitting a 1D Gaussian centered at $r=0$ to the radial profile:

$$ P(r) \approx A \exp\!\left(-\frac{r^2}{2\sigma^2}\right) + B, \qquad
   \mathrm{FWHM} = 2\sqrt{2\ln 2}\;\sigma \approx 2.3548\,\sigma. $$

For a perfectly Gaussian, unsaturated optical system, the curve of growth $C(r)$ converges to
the star's total flux as $r \to \infty$; in practice it plateaus well before `max_radius` as long
as the chosen max radius is large enough.

## Parameters

- **`max_radius`** — *int*, default `15`, range `3`–`200`. Maximum radius (in pixels) sampled
  for the radial profile and curve of growth. It should comfortably cover the Airy
  disk/halo of the star under study; too small and both the FWHM and flux saturation are
  underestimated, too large and a neighboring source or background noise dilutes the profile.

## Tips & pitfalls

> **Warning** — the center is chosen as the **brightest pixel of the entire image**, with no
> source detection. On a crowded field, or with a hot pixel present, isolate the target star
> first in a cropped **preview** before running the measurement.

> **Note** — the measurement does not subtract the sky background. On an image with an elevated
> background (light pollution, gradient), the fitted FWHM can be biased; run
> `BackgroundExtraction` or `BackgroundNeutralization` first.

- If `.result["fwhm"]` is `None`, the profile was too flat or degenerate (often a saturated,
  flat-topped star, or too small a `max_radius`): widen the radius or check the centering.
- For an average statistical FWHM over several stars (global quality control, autofocus),
  prefer `DynamicPSF`, which fits a 2D Gaussian over a batch of detected stars.

## See also

- [DynamicPSF](retina-doc://DynamicPSF) — average FWHM and eccentricity over several detected stars.
- [Statistics](retina-doc://Statistics) — global robust image statistics.
- [SubframeSelector](retina-doc://SubframeSelector) — quality sorting/scoring of a batch of frames.

## References

- photutils.profiles — *RadialProfile* and *CurveOfGrowth*.
- PixInsight — PSF/star profile inspection tools.
