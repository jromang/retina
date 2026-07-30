---
id: Statistics
category: Image
title: Statistics
brief: Reads robust estimators (mean, median, mad_std, biweight) per channel, without modifying the image.
keywords: [statistics, median, mad_std, biweight, robust estimator, inspection, noise]
related: [SubframeSelector, LinearFit, Integration, HistogramTransformation]
icon: chart-dots
references:
  - "astropy.stats — mad_std, biweight_location."
  - "PixInsight — Statistics process reference."
---

## Summary

`Statistics` computes a set of **robust estimators** (mean, median, robust standard deviation
`mad_std`, biweight location, minimum, maximum) for every channel of the active image, and
stores them in `self.result`. It is a **pure read** process: it writes no pixels and pushes no
history entry — it is an inspection tool, the equivalent of PixInsight's *Statistics* panel,
built here on `astropy.stats` rather than a hand-rolled implementation.

## Use cases

- **Diagnose the sky background level** before `BackgroundExtraction` or
  `BackgroundNeutralization` (per-channel median).
- **Estimate noise** in an image or an individual sub (`mad_std`) to compare frames before
  integration, or to calibrate rejection thresholds for `Integration`.
- **Check a stretch** (`HistogramTransformation`, `AutoHistogram`): the median should land in a
  target range after stretching, with no visible clipping in min/max.
- **Script quality control**: the console can read `Statistics().execute_on(view).result` and
  chain a decision (frame rejection, saturation warning) without ever going through the GUI.

## How it works

The process reads the image data (`image.data`, a `(H, W, C)` array), then, **channel by
channel**, computes six quantities using `numpy` and `astropy.stats`:

1. `mean` and `median` — the classical center and the robust center (`numpy.mean` /
   `numpy.median`).
2. `mad_std` — robust standard deviation derived from the median absolute deviation
   (`astropy.stats.mad_std`).
3. `biweight` — Tukey's biweight location estimator (`astropy.stats.biweight_location`), which
   weights samples by their distance to the center and discounts extreme values more smoothly
   than a hard clip.
4. `min` / `max` — raw channel bounds (useful to spot saturation or negative values).

The result is a dictionary `{"channels": {0: {...}, 1: {...}, ...}}` stored in `self.result`;
nothing else changes. `execute_on(view)` does not wrap a `begin_process()/end_process()` pair —
per the code's own comment, a read does not create a history entry. `execute_on_image(image)`
does the same in pure headless mode, without a `View`, and returns the image unchanged (handy
in an `app.run` pipeline).

## Mathematics

For a channel $\{x_i\}_{i=1}^{N}$, the process reports the classical center and the robust
center:

$$ \bar{x} = \frac{1}{N}\sum_{i=1}^{N} x_i, \qquad \tilde{x} = \operatorname{med}(x_i). $$

The robust standard deviation `mad_std` is built on the median absolute deviation (MAD), scaled
by the factor $1.4826$ that makes it consistent with the standard deviation of a normal
distribution:

$$ s = \operatorname{mad\_std}(x_i) = 1.4826 \cdot \operatorname{med}\!\big(|x_i - \tilde{x}|\big). $$

Tukey's biweight estimator refines the central position further by progressively down-weighting
distant points. With $u_i = (x_i - \tilde{x}) / (c\,s)$ ($c = 6$ by default in `astropy`), and
keeping only the $i$ with $|u_i| < 1$:

$$ \operatorname{biweight}(x_i) = \tilde{x} +
   \frac{\sum_i (x_i - \tilde{x})\,(1 - u_i^2)^2}{\sum_i (1 - u_i^2)^2}. $$

Unlike the mean, `mad_std` and `biweight` stay stable in the presence of saturated stars, hot
pixels, or satellite trails: a handful of extreme samples does not drag these estimators, unlike
the classical mean or standard deviation.

## Parameters

This process has **no parameters**. It only acts on the target view's image and always computes
the same set of estimators, channel by channel.

## Tips & pitfalls

> **Note** — statistics are computed on the image's **raw current values**, whether linear or
> already stretched, depending on the view's current state. Comparing medians between a linear
> image and a stretched one is meaningless: rerun `Statistics` after each significant stretch.

- `mad_std` is a far better noise indicator than the classical standard deviation as soon as
  stars or artifacts are present in the field — it is the same estimator `Integration` uses for
  its sigma rejection.
- A `max` close to 1.0 (normalized image) on several channels signals saturation worth watching
  before integration or color calibration.
- To inspect a region rather than the whole image, run `Statistics` on a `Preview`: the API is
  strictly identical (a `Preview` **is** a `View`).

## See also

- [SubframeSelector](retina-doc://SubframeSelector) — per-frame quality metrics (noise, FWHM, eccentricity).
- [LinearFit](retina-doc://LinearFit) — scale fitting between images based on robust statistics.
- [Integration](retina-doc://Integration) — uses median and mad_std for sigma rejection.
- [HistogramTransformation](retina-doc://HistogramTransformation) — stretch to check via these statistics.

## References

- astropy.stats — *mad_std*, *biweight_location*.
- PixInsight — *Statistics* process reference.
