---
id: SEPSourceExtraction
category: ImageInspection
title: SEP Source Extraction
brief: Very fast source catalog (background + detection) via the sep library (native Source-Extractor).
keywords: [source detection, catalog, SExtractor, sep, stars, isophotal photometry, quality control]
related: [SEPBackground, SourceExtraction, StarMask, DynamicPSF]
icon: scan
references:
  - "Bertin, E. & Arnouts, S. (1996) — SExtractor: Software for source extraction."
  - "Barbary, K. — sep: Source Extraction and Photometry (Python documentation)."
  - "PixInsight — DynamicPSF / StarAlignment (star detection)."
---

## Summary

`SEPSourceExtraction` builds a **source catalog** (position, flux, area) using the `sep` library —
the Python/C port of the native **SExtractor** engine. It is the "Tier B" detection path in
Retina: much faster than `SourceExtraction` (photutils), at the cost of a simpler background
model and deblending. The process is **read-only**: it never modifies pixel values, only
`self.result`.

## Use cases

- **Fast quality control** of a batch of subframes (number of detected sources, field density)
  without the cost of a full photutils background model.
- **Preprocessing** before registration or stacking: feed a list of candidate positions to
  `StarAlignment` or an external star mask.
- **Session monitoring**: compare the source count frame by frame to spot degraded exposures
  (passing clouds, focus drift, excess noise).
- **Very dense or very large fields** where `SourceExtraction` (photutils) becomes too slow.

## How it works

1. The image is reduced to a 2D **luminance** (channel average if color) and cast to a contiguous
   `float32` array, the format required by `sep`.
2. `sep.Background` estimates a **sky background** over a mesh grid (`sep` defaults: 64×64 px
   boxes, 3×3 median filter), with SExtractor-style outlier rejection, then interpolates it into a
   smooth surface.
3. The background is subtracted from the luminance (`sub = lum - bkg.back()`), and its global
   standard deviation (`bkg.globalrms`) is used as the reference noise level.
4. `sep.extract` thresholds the subtracted image at `threshold_sigma` times that noise, groups
   connected pixels into objects (minimum area `min_area`), and automatically **deblends** merged
   sources via multi-level thresholding (the standard SExtractor algorithm).
5. For each retained object, the position is the **intensity-weighted centroid**, the flux is the
   isophotal sum of pixels above threshold, and the area is the pixel count of the segment. The
   result is stored in `self.result = {"n_sources": ..., "sources": [...]}`.

## Mathematics

Let $I(x,y)$ be the luminance and $B(x,y)$ the background model produced by `sep.Background`. The
subtracted image is $S(x,y) = I(x,y) - B(x,y)$, and $\sigma$ (`bkg.globalrms`) the global standard
deviation estimated over that same surface. A pixel is **detected** when it exceeds the threshold:

$$ S(x,y) > t \cdot \sigma, \qquad t = \texttt{threshold\_sigma} $$

Adjacent detected pixels (8-connectivity) form an object once its pixel count
$N \ge \texttt{min\_area}$. For an object with pixels $\{(x_i, y_i)\}_{i=1}^{N}$, the isophotal
flux and intensity-weighted centroid are:

$$ F = \sum_{i=1}^{N} S(x_i, y_i), \qquad
   \bar{x} = \frac{\sum_i x_i\, S(x_i, y_i)}{\sum_i S(x_i, y_i)}, \qquad
   \bar{y} = \frac{\sum_i y_i\, S(x_i, y_i)}{\sum_i S(x_i, y_i)} $$

When two sources touch, `sep.extract` re-tests each object against a series of exponentially
spaced sub-thresholds between the peak and $t\sigma$; a branch is split into a separate object as
soon as its flux exceeds a fraction (0.5% by default) of the parent branch's total flux — this is
the **multi-threshold deblending** inherited from SExtractor.

## Parameters

- **`threshold_sigma`** — *real*, default `3.0`, range `0.5`–`50.0`. Detection threshold expressed
  as multiples of the background's global standard deviation (`bkg.globalrms`). Lower values
  detect fainter sources at the cost of more false positives in the noise.
- **`min_area`** — *int*, default `5`, range `1`–`1000`. Minimum number of connected pixels above
  threshold for a group to be kept as a source. Filters out single-pixel noise and point-like
  cosmic ray hits.

## Tips & pitfalls

> **Warning** — the default `sep.Background` uses 64 px boxes with no tunable exposed here: on a
> field with a strong gradient (vignetting, marked light pollution), run `SEPBackground` or
> `BackgroundExtraction` first, then extract sources on the already-flattened image for a more
> reliable residual background.

> **Note** — `bkg.globalrms` is a single **global** noise value for the whole image: unlike
> `SourceExtraction` (photutils), no local noise map is used. On an image with strongly
> heterogeneous noise (mosaic, partial stack), the threshold can be too permissive in noisy areas
> and too strict in quiet ones.

- The result includes neither ellipticity nor orientation (unlike `SourceExtraction`): for a star
  mask or shape measurement, use `StarMask` or `DynamicPSF` instead.
- For a quick count on very large images (mosaics, wide field), this is the cheapest path in the
  Retina catalog.

## See also

- [SEPBackground](retina-doc://SEPBackground) — same `sep` library, to flatten the background upstream.
- [SourceExtraction](retina-doc://SourceExtraction) — equivalent catalog via photutils (deblending and ellipticity).
- [StarMask](retina-doc://StarMask) — binary star mask from a similar detection.
- [DynamicPSF](retina-doc://DynamicPSF) — per-star profile measurement (FWHM, shape).

## References

- Bertin, E. & Arnouts, S. (1996) — *SExtractor: Software for source extraction*.
- Barbary, K. — *sep: Source Extraction and Photometry* (Python documentation).
- PixInsight — *DynamicPSF* / *StarAlignment* (star detection).
