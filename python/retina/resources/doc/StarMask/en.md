---
id: StarMask
category: MaskGeneration
title: Star Mask
brief: Detects stars (photutils DAOStarFinder) and produces a binary disk mask in a new window.
keywords: [mask, stars, detection, DAOStarFinder, protection, PSF]
related: [StarAlignment, StarRemoval, DynamicPSF, SEPSourceExtraction]
icon: star
references:
  - "PixInsight — StarMask tool reference."
  - "Stetson, P. B. (1987) — DAOPHOT: A Computer Program for Crowded-Field Stellar Photometry, PASP 99."
  - "photutils.detection — DAOStarFinder."
---

## Summary

`StarMask` automatically detects the stars in the active image (Stetson's DAOFIND algorithm,
via `photutils.detection.DAOStarFinder`) and builds a **binary mask** (1 channel) made of disks
centered on every detected star. It is non-destructive in the strict sense: it never touches
the source image but **creates a new window** holding the mask, ready to be applied to another
process in order to protect — or, conversely, to target — the stars. The detection catalog from
the last run stays available through the instance's `.stars` attribute.

## Use cases

- **Protect the stars** during aggressive noise reduction or deconvolution: apply the mask
  (optionally inverted) to `NoiseReduction` or `Deconvolution` to spare stellar cores.
- **Target only the stars** for a dedicated treatment (chromatic halo reduction, spot
  correction) without touching the sky background or nebulosity.
- **Feed `StarRemoval`** or an LRGB / stars-nebulae combination by geometrically isolating the
  stellar regions.
- **Diagnose the detection**: inspect `.stars` (an astropy table) to check the number of stars
  found and their coordinates before pushing the processing further.

## How it works

Processing happens in three steps:

1. **Reduction to a 2D luminance plane**: the per-channel mean (`data.mean(axis=2)`) is used as
   the detection plane, regardless of how many channels the source image has.
2. **Detection (DAOFIND)**: robust background statistics (median, standard deviation) are
   estimated through iterative 3σ sigma-clipping (`astropy.stats.sigma_clipped_stats`), then
   `DAOStarFinder` runs on the recentered image (`lum - median`) with a Gaussian kernel matched
   to `fwhm` and an absolute threshold of `threshold_sigma * std`. The algorithm correlates the
   image with that kernel, keeps local maxima exceeding the threshold, and filters out false
   positives (cosmic rays, hot pixels, extended sources) using DAOFIND's sharpness and roundness
   criteria.
3. **Painting the mask**: for every detected star (centroid `xcentroid`/`ycentroid`), a disk of
   radius `radius` is painted `True` into a boolean mask the size of the image; the result is
   cast to `float32` and exposed as a 1-channel image in the newly created window.

## Mathematics

Let $L(x,y)$ be the luminance plane and $\tilde{L}$, $\sigma_L$ its robust median and standard
deviation (3σ sigma-clipping). The detection threshold is:

$$ t = \texttt{threshold\_sigma} \cdot \sigma_L. $$

DAOFIND correlates $L - \tilde{L}$ with a Gaussian kernel whose standard deviation is derived
from the requested full width at half maximum:

$$ \sigma_{\text{PSF}} = \frac{\texttt{fwhm}}{2\sqrt{2\ln 2}}, \qquad
   K(x,y) = \exp\!\left(-\frac{x^2+y^2}{2\sigma_{\text{PSF}}^2}\right), $$

and keeps positions $(x_0,y_0)$ where the correlated response exceeds $t$ and forms a local
maximum, provided the peak's shape statistics (sharpness, roundness) match a plausible
point-like profile rather than an artifact.

For every retained star with center $(c_x, c_y)$, the final mask is:

$$ M(x,y) = \bigvee_{i} \mathbb{1}\!\left[(x - c_{x,i})^2 + (y - c_{y,i})^2 \le
   \texttt{radius}^2\right] \in \{0, 1\}, $$

the union (logical OR) running over every star $i$ in the detected catalog.

## Parameters

- **`fwhm`** — *real*, default `3.0`, range `1`–`20`. Full width at half maximum (in pixels) of
  the Gaussian profile used for detection. It should match the image's actual star FWHM: too
  small and it fragments large stars into several detections or picks up noise; too large and
  it misses thin stars or merges nearby ones.
- **`threshold_sigma`** — *real*, default `5.0`, range `1`–`50`. Detection threshold, expressed
  as multiples of the background's robust standard deviation. Higher values keep fewer faint
  stars (fewer false positives, but an incomplete catalog).
- **`radius`** — *real*, default `4.0`, range `1`–`50`. Radius (in pixels) of the disks painted
  around each detected centroid. Controls how thick the mask's protection/targeting is,
  independently of the actual star size.

## Tips & pitfalls

> **Warning** — the `threshold_sigma` threshold applies to the standard deviation of the
> **whole** image's background; on a field with a strong gradient (vignetting, light
> pollution), the background is not uniform and detection can be biased. Flatten the background
> first with `BackgroundExtraction` for a more reliable detection.

- The mask radius does not need to match the FWHM: a generous `radius` also protects the
  stellar profile's wings (halo), useful before aggressive noise reduction.
- A very noisy image with `threshold_sigma` set too low generates many false positives (photon
  noise interpreted as stars): check `.stars` after running.
- The mask is computed from the **average channel luminance**: on an unbalanced color image
  (strong R/G/B imbalance), detection can favor the dominant channel.
- Remember to invert the mask (`Invert`) if the goal is to protect the stars rather than to
  target them.

## See also

- [StarAlignment](retina-doc://StarAlignment) — registration by star matching.
- [StarRemoval](retina-doc://StarRemoval) — star removal via inpainting.
- [DynamicPSF](retina-doc://DynamicPSF) — interactive measurement of the actual star profile (FWHM).
- [SEPSourceExtraction](retina-doc://SEPSourceExtraction) — alternative source extraction (SEP).

## References

- PixInsight — *StarMask* tool reference.
- Stetson, P. B. (1987) — *DAOPHOT: A Computer Program for Crowded-Field Stellar Photometry*, PASP 99.
- photutils.detection — *DAOStarFinder*.
