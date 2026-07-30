---
id: LinearDefectDetection
category: ImageInspection
title: Linear Defect Detection
brief: Finds columns and rows whose level departs from their neighbours, and exports the list.
keywords: [banding, columns, rows, CMOS, defects, LPS, sensor, JSON]
related: [LinearPatternSubtraction, CosmeticCorrection, DefectMap, NoiseEvaluation]
icon: line
references:
  - "PixInsight — LinearDefectDetection script."
---

## Summary

`LinearDefectDetection` serves two purposes: **seeing** whether your sensor produces a column
pattern (defects are drawn in the viewport), and producing the **list** that
[LinearPatternSubtraction](retina-doc://LinearPatternSubtraction) will correct in conservative
mode.

The pattern is a property of the **sensor**, not of the frame: measure it once, on a calibrated
frame or a master, and reuse the list for the whole series.

## How it works

For each column, the median of its pixels — that is, the sky background at that place, stars and
nebulae being a minority there. That median is then compared with the **local trend** of its
neighbours (median filter), and departures exceeding `threshold_sigma` robust deviations are
kept.

On an undebayered CFA image, tick `cfa`: every other column sees a different filter, and without
it the differences between colours would be reported.

## What a false positive costs

Nothing, or nearly. A column flagged in error will be corrected by an amount **below the
noise**. The threshold therefore needs no fine tuning; `5.0` comfortably separates a real
pattern (a hundred times the dispersion) from the fluctuation of a column median.

## Parameters

- **`columns`** / **`rows`** — *bool*, defaults `True` / `False`.
- **`threshold_sigma`** — *real*, default `5.0`. Threshold in robust deviations.
- **`cfa`** — *bool*, default `False`. Undebayered CFA image.
- **`output_path`** — *path*. Writes the list as JSON (`{version, defects: [{axis, index,
  offset, sigma}]}`).
- **`show_defects`** — *bool*, default `True`. Draw defects in the viewport.

Read-only; result in `.result`.

## See also

- [LinearPatternSubtraction](retina-doc://LinearPatternSubtraction) — correct what was just
  found.
- [DefectMap](retina-doc://DefectMap) — a supplied defect map, pixel by pixel.
- [NoiseEvaluation](retina-doc://NoiseEvaluation) — to know what "a departure below the noise"
  compares against.

## References

- PixInsight — *LinearDefectDetection* script.
