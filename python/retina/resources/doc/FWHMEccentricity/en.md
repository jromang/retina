---
id: FWHMEccentricity
category: ImageInspection
title: FWHM and Eccentricity Map
brief: Measures star FWHM and eccentricity cell by cell, and draws the field map.
keywords: [FWHM, eccentricity, focus, collimation, tilt, tracking, optical quality, field map]
related: [DynamicPSF, AberrationInspector, SubframeSelector, Deconvolution]
icon: grid-dots
references:
  - "PixInsight — FWHMEccentricity script."
---

## Summary

A median FWHM says very little: an image can be excellent in the centre and soft in one corner,
and that is exactly what you want to know. `FWHMEccentricity` therefore splits the field into
`grid` × `grid` cells and returns, for each, the median over its stars — then draws the map in
the viewport.

**Eccentricity** is even more telling than FWHM. It betrays two defects that are often confused:

- elongation in a **direction common** to the whole field is **tracking** (drift, wind,
  periodic error);
- **radial** elongation, weak at the centre and growing towards the edges, is **optics** —
  sensor tilt, field curvature, coma.

Hence the ellipses drawn at the measured orientation: a map of numbers would not show the
direction, which is most of the diagnosis.

## Use cases

- **Check focus** before committing to a night of acquisition.
- **Diagnose tilt** of the sensor or focuser: the map makes it obvious in one run, where
  comparing four corners at zoom requires remembering what you just saw.
- **Choose `psf_sigma`** for [deconvolution](retina-doc://Deconvolution) — though there,
  `psf_mode = measured` does the job by itself.

## How it works

1. Star detection (`DAOStarFinder`), **brightest first**: with a bounded number of fits, those
   are the stars whose shape is best constrained.
2. An elliptical PSF is fitted to each — this is `fit_psf_stars`, the fitter shared with
   `DynamicPSF` and `SubframeSelector`. Writing a second fitter would have guaranteed they
   diverge, on the very quantity used to judge.
3. Median per cell. A cell with no fittable star is returned **empty** rather than omitted: a
   hole in the map is information.
4. If `show_map`, ellipses and values are placed as overlays on the window.

The drawn ellipses are **scaled up by a common factor**: at true scale, a three-pixel FWHM on a
six-thousand-pixel image is invisible. What matters is the comparison between cells; the
absolute value is written alongside.

## Parameters

- **`fwhm`** — *real*, default `3.0`. Approximate FWHM for detection, in pixels.
- **`threshold_sigma`** — *real*, default `5.0`. Detection threshold in background σ.
- **`max_stars`** — *int*, default `300`. Number of fits. Beyond a few hundred you mostly buy
  computation time.
- **`grid`** — *int*, default `5`. The field is split into `grid` × `grid` cells.
- **`psf_model`** — *enum* `gaussian` | `moffat`, default `gaussian`. The Moffat has longer
  wings, often closer to real seeing.
- **`show_map`** — *bool*, default `True`. Draw the map in the viewport.

Read-only: no pixel is modified, no history entry is created. The result is in `.result` —
global medians, per-star detail, and the grid of cells.

## Tips & pitfalls

> **High but uniform eccentricity is not an optical defect.** First check whether the ellipse
> direction is the same everywhere: if it is, look at tracking.

- A cell with one or two stars gives a fragile median. Raise `max_stars`, or lower `grid`:
  three honest cells beat eight uncertain ones.
- On an already-stretched image, detection finds too many faint stars; raise
  `threshold_sigma`.

## See also

- [DynamicPSF](retina-doc://DynamicPSF) — the same measurement, star by star and on click.
- [AberrationInspector](retina-doc://AberrationInspector) — corners side by side, to see rather
  than measure.
- [SubframeSelector](retina-doc://SubframeSelector) — the same measurement, over a batch.

## References

- PixInsight — *FWHMEccentricity* script.
