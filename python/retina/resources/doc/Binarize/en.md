---
id: Binarize
category: IntensityTransformations
title: Binarize
brief: Converts every pixel to all-or-nothing (0 or 1) by comparison against a single threshold.
keywords: [binarize, threshold, thresholding, mask, all-or-nothing]
related: [RangeSelection, HistogramTransformation, StarMask, Invert]
icon: binary
references:
  - "PixInsight — Binarize tool reference."
  - "Global thresholding — classic image processing (Otsu, fixed threshold)."
---

## Summary

`Binarize` turns an image into a **strictly binary** map: each sample becomes `1.0` if it
meets or exceeds a single **threshold**, `0.0` otherwise. It is the simplest possible
thresholding operation — no gradient, no transition zone — applied independently to each
channel. The result is pure black and white, useful as a building block for making masks or
isolating structures above or below a given level.

## Use cases

- **Build a rough mask** (galaxy silhouette, halo, saturated area) before refining it with
  dilation/erosion (`MorphologicalTransformation`) or blurring.
- **Isolate saturated pixels** by binarizing on a threshold close to 1, to count them or
  exclude them from a statistics computation.
- **Detect the presence of signal** above the background noise once a threshold has been
  estimated (e.g. median + k·MAD via `Statistics`), as preparation for source detection.
- **Create teaching or debugging binary maps** to visualize where an intensity condition
  holds true or false across the image.

## How it works

The operator compares every pixel value, channel by channel, against the `threshold` parameter:

1. Input data is assumed to be normalized to `[0, 1]` (Retina/PixInsight convention).
2. Each sample `x` is tested independently: `x >= threshold`.
3. The output is written as `1.0` (true) or `0.0` (false), in `float32`.

There is no smoothing and no edge interpolation: the transition is a perfect **step**. The
process is applied to the whole image (or the active preview) and can be combined with an
application mask (`is_maskable = True`) to binarize only a region.

## Mathematics

For a pixel value $x \in [0,1]$ and a threshold $t$ = `threshold`, the output is the step
function (a shifted Heaviside function):

$$ b(x) = \begin{cases} 1 & \text{if } x \ge t \\ 0 & \text{if } x < t \end{cases} $$

Applied independently to each channel $c$ and each position $(u, v)$:

$$ I'_{c}(u,v) = b\big(I_{c}(u,v)\big) = \mathbb{1}_{\,I_{c}(u,v) \,\ge\, t} $$

where $\mathbb{1}$ is the indicator function. This operation is **non-linear, non-invertible**
(irreversible: all gradation information is lost) and **idempotent** — binarizing twice in a
row with the same threshold changes nothing after the first pass, since the output already
contains only $\{0, 1\}$.

## Parameters

- **`threshold`** — *real*, default `0.5`, range `0`–`1`. Comparison threshold: any pixel
  whose value is greater than or equal to it becomes white (`1.0`), everything else becomes
  black (`0.0`). A low threshold keeps more pixels at `1`; a high threshold keeps very few
  (typically star cores or saturated areas).

## Tips & pitfalls

> **Warning** — the operation is destructive and **irreversible**: every shade between 0 and
> 1 disappears. Work on a copy of the view, or downstream of a mask, if the original image
> needs to remain available.

> **Note** — the threshold is applied per channel on a color image: a single `threshold`
> value can binarize R, G and B at visually different points. For a luminance-based threshold
> with a soft transition, prefer `RangeSelection`.

- On a linear, unstretched image most of the signal sits close to 0: a `threshold` of 0.5
  will often keep almost nothing. Stretch the image (`HistogramTransformation`, STF) or
  compute a noise-adapted threshold before binarizing.
- For a mask with progressive edges (less aggressive than a hard threshold), `RangeSelection`
  offers a `fuzziness` parameter and optional Gaussian smoothing.

## See also

- [RangeSelection](retina-doc://RangeSelection) — intensity-range selection with soft edges.
- [HistogramTransformation](retina-doc://HistogramTransformation) — prior stretch to position
  the signal before thresholding.
- [StarMask](retina-doc://StarMask) — dedicated star mask generation.
- [Invert](retina-doc://Invert) — complementary inversion of a binarized result.

## References

- PixInsight — *Binarize* tool reference.
- Global thresholding — classic image processing (Otsu, fixed threshold).
