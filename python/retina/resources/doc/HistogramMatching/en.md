---
id: HistogramMatching
category: ColorCalibration
title: Histogram Matching
brief: Aligns a view's intensity distribution onto that of a reference view (skimage).
keywords: [histogram, matching, mosaic, integration, sky background, normalization]
related: [LinearFit, StarAlignment, Integration, MosaicReproject]
icon: chart-histogram
references:
  - "scikit-image — skimage.exposure.match_histograms."
  - "Gonzalez & Woods — Digital Image Processing, histogram specification."
---

## Summary

`HistogramMatching` reshapes a view's intensity distribution so it matches that of a
**reference view**, channel by channel, using scikit-image's `match_histograms`. Unlike
`HistogramTransformation`, which applies a parametric tonal curve (MTF), this operation
copies the **cumulative histogram** of another image: it is the tool to reach for when you
need to unify the background and color balance across several frames before merging them
(mosaic, integration, panorama).

## Use cases

- **Unify several exposures** of the same target taken under different dates or sky
  conditions (transparency, light pollution) before integration.
- **Blend mosaic tiles** so neighboring panels share the same sky background and color
  balance before merging (`MosaicReproject`, `GradientMergeMosaic`).
- **Reproduce the tonal look** of a reference image (an already-validated rendering) on a
  new frame of the same object.
- **Rescale the dynamic range** of an underexposed image onto a well-exposed reference
  frame before combining.

## How it works

The process takes a single parameter: the identifier of the **reference view**
(`reference`). Without a valid reference (empty string or view not found), the image is
returned **unchanged** (a plain copy).

Once a reference is resolved:

1. If the reference has the same number of channels as the source image, matching is done
   in one pass across all channels at once (`channel_axis=-1`), which preserves the
   correlations between color channels.
2. Otherwise (e.g. a monochrome reference for an RGB source), matching is done
   **channel by channel**: each source channel is matched to the corresponding reference
   channel, reusing the reference's last available channel if it has fewer channels than
   the source (`min(c, ref_channels - 1)`).
3. The result is **clipped** to `[0, 1]` and cast back to `float32`.

The underlying algorithm (`skimage.exposure.match_histograms`) computes, for each channel,
the normalized cumulative histogram of the source and of the reference, then builds a
mapping function that sends each source value to the reference value sharing the same
cumulative rank.

## Mathematics

For a given channel, let $F_s$ be the empirical **cumulative distribution function** (CDF)
of the source pixel values, and $F_r$ that of the reference:

$$ F_s(x) = \frac{\#\{\, i : x_i \le x \,\}}{N_s}, \qquad
   F_r(y) = \frac{\#\{\, j : y_j \le y \,\}}{N_r}. $$

Histogram matching finds, for every source value $x$, the output value $y$ sharing the same
**cumulative rank**:

$$ y = F_r^{-1}\!\big(F_s(x)\big). $$

In practice, $F_s$ and $F_r$ are step functions built from the distinct observed values;
$F_r^{-1}$ is obtained by interpolating between the reference values whose CDF brackets
$F_s(x)$. By construction, the result has a histogram whose cumulative shape matches the
reference (up to quantization effects), which equalizes both the **mean level** (sky
background) and the **contrast** (tonal spread) between the two images.

## Parameters

- **`reference`** — *str*, default `""`. Identifier of the reference view whose cumulative
  histogram is the target. Empty string or unresolved identifier → the image is returned
  unmodified.

## Tips & pitfalls

> **Warning** — the reference must have **comparable framing/content** (same field, similar
> proportion of sky background versus signal). Matching against very different content
> (e.g. a star-dense field versus a nebula-dominated field) can introduce posterization
> artifacts.

> **Note** — without a resolvable reference, the process is a **silent no-op**: check that
> `reference` names an open, non-empty view.

- For a simple level recalibration (gain/offset) without redistributing the histogram's
  shape, prefer `LinearFit`, which is gentler and less prone to artifacts on low background
  noise.
- Run the matching **before** integration or mosaic assembly, not after: it prepares
  consistent frames, it does not fix an already-combined result.
- On images with strong background noise, matching can locally amplify noise if the source
  and reference histograms differ greatly in shape; check the result under a mask if
  needed.

## See also

- [LinearFit](retina-doc://LinearFit) — gentler linear (least-squares) level matching.
- [StarAlignment](retina-doc://StarAlignment) — geometric registration prior to merging.
- [Integration](retina-doc://Integration) — stacking frames once unified.
- [MosaicReproject](retina-doc://MosaicReproject) — WCS reprojection to assemble a mosaic.

## References

- scikit-image — *skimage.exposure.match_histograms*.
- Gonzalez & Woods — *Digital Image Processing*, histogram specification.
