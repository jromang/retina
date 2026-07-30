---
id: SourceExtraction
category: ImageInspection
title: Source Extraction
brief: "Source catalogue (segmentation + deblending, photutils) — read-only."
keywords: [star detection, segmentation, deblending, catalogue, SExtractor, photometry, star mask]
related: [SEPSourceExtraction, StarMask, DynamicPSF, Statistics]
icon: scan
references:
  - "Bertin, E. & Arnouts, S. (1996) — SExtractor: Software for source extraction."
  - "photutils — Image Segmentation (detect_sources, deblend_sources, SourceCatalog)."
---

## Summary

`SourceExtraction` builds a **source catalogue** from an image, SExtractor-style:
threshold-based segmentation of the background, **deblending** of merged sources, then
measurement of each object's properties (position, flux, area, ellipticity). This is a
**read-only** process — like `Statistics` — that never modifies the pixels: it deposits its
result in the instance's `.result` attribute rather than in the view history. The engine is
`photutils` (connected-region segmentation), robust and well documented, at a higher
computational cost than the native `sep` path (see `SEPSourceExtraction`).

## Use cases

- **Build a star mask** on a dense field, as a starting point for `StarMask` or to manually
  isolate point sources before star removal.
- **Quality control of a sub-exposure**: count detected sources, check their average
  ellipticity (tracking/focus quality), or flag a field too star-poor for alignment.
- **Photometric starting point**: quickly obtain fluxes and centroids ahead of finer
  processing (`DynamicPSF` for a PSF model, or a dedicated photometric calibrator).
- **Diagnose a poorly subtracted background**: an unusually high source count after
  `BackgroundExtraction` often betrays residual background noise mistaken for signal.

## How it works

1. The image is reduced to a **luminance map** (channel average for colour images).
2. Background and noise are estimated by **robust sigma-clipping**
   (`astropy.stats.sigma_clipped_stats`), yielding a median and standard deviation largely
   insensitive to the stars themselves.
3. A **detection threshold** is set at `threshold_sigma` standard deviations above the
   background median; `detect_sources` (photutils) segments the image into connected regions
   of pixels above that threshold, each region requiring at least `npixels` adjacent pixels.
4. If `deblend` is enabled, `deblend_sources` splits regions that actually correspond to
   several overlapping sources (close stars, a galaxy core) via multi-threshold re-analysis
   of each blob. If deblending fails to converge, the raw segmentation is kept without
   interrupting processing.
5. `SourceCatalog` measures, for each region, the **centroid**, **integrated flux** (sum of
   the segment's pixels, background-subtracted), **area**, and **eccentricity** of the
   equivalent ellipse.
6. The result is stored in `self.result`: `{"n_sources": int, "sources": [...]}`, each entry
   being a dict `{x, y, flux, area, eccentricity}`. No history entry is created — the view is
   left unchanged.

## Mathematics

The per-pixel detection threshold is linear in the robust background:

$$ T = \tilde{b} + \kappa \cdot \sigma_b, $$

where $\tilde{b}$ and $\sigma_b$ are the median and standard deviation of the background
after iterative outlier rejection (sigma-clipping at $3\sigma$), and $\kappa$ =
`threshold_sigma`. A pixel belongs to a **candidate source** if its value exceeds $T$; a
connected region of above-threshold pixels only forms a valid segment once its size reaches
`npixels`.

For a segmented source occupying the pixel set $\Omega$, the measured flux is the sum of the
background-subtracted signal:

$$ F = \sum_{(x,y)\,\in\,\Omega} \big(I(x,y) - \tilde{b}\big). $$

The intensity centroid is the flux-weighted average:

$$ \bar{x} = \frac{1}{F}\sum_{(x,y)\in\Omega} x\,\big(I(x,y)-\tilde b\big), \qquad
   \bar{y} = \frac{1}{F}\sum_{(x,y)\in\Omega} y\,\big(I(x,y)-\tilde b\big). $$

**Eccentricity** derives from the second-order moments of the intensity distribution (the
$2\times2$ covariance matrix of positions weighted by flux): denoting $\lambda_1 \ge
\lambda_2$ its eigenvalues (variances along the equivalent ellipse's principal axes),

$$ e = \sqrt{1 - \frac{\lambda_2}{\lambda_1}}. $$

$e = 0$ corresponds to a perfectly round source (ideal stellar PSF), $e \to 1$ to a strongly
elongated shape (trailed star, satellite streak, edge-on galaxy).

## Parameters

- **`threshold_sigma`** — *real*, default `3.0`, range `0.5`–`50.0`. Detection threshold in
  robust standard deviations above the background median. Too low: background noise gets
  detected as sources; too high: only the brightest sources survive.
- **`npixels`** — *int*, default `5`, range `1`–`1000`. Minimum number of connected pixels
  above the threshold required to validate a detection. Filters isolated hot pixels and
  point-like noise; too high a value discards the faintest or undersampled stars.
- **`deblend`** — *bool*, default `True`. Splits sources merged into a single segmented
  region (close stars, clusters). Computationally costly on very dense fields; can be
  disabled for a quick quality check where exact counts matter less.

## Tips & pitfalls

> **Warning** — `SourceExtraction` **never modifies** the image and **does not open a
> history entry**: it is a pure measurement process. Its result lives only in the `.result`
> attribute of the instance that ran it; it is not persisted anywhere else.

> **Note** — on large fields or in batch processing, `SEPSourceExtraction` (built on the
> `sep` library, a native Source-Extractor port) is significantly faster for a qualitatively
> similar result, at the cost of a leaner output table (no ellipticity).

- Always run on an image with an already reasonably flat background
  (`BackgroundExtraction`): a residual gradient biases the sigma-clipping and artificially
  inflates or shrinks the detection count.
- For a quality star mask, prefer `StarMask`, which wraps a similar detection but directly
  produces an image mask rather than a catalogue.
- Eccentricity alone cannot distinguish a trailed star from an elongated galaxy: cross-check
  with area and, if needed, visually inspect the most eccentric sources.

## See also

- [SEPSourceExtraction](retina-doc://SEPSourceExtraction) — equivalent detection, very fast `sep` engine.
- [StarMask](retina-doc://StarMask) — binary star mask derived from a similar detection.
- [DynamicPSF](retina-doc://DynamicPSF) — fine PSF modelling on chosen stars.
- [Statistics](retina-doc://Statistics) — another pure, read-only measurement process.

## References

- Bertin, E. & Arnouts, S. (1996) — *SExtractor: Software for source extraction*.
- photutils — *Image Segmentation* (`detect_sources`, `deblend_sources`, `SourceCatalog`).
