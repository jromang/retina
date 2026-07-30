---
id: SubframeSelector
category: ImageInspection
title: Subframe Selector
brief: Measures FWHM, star count, background noise and a SNR proxy per frame to compute a relative weight.
keywords: [quality, FWHM, frame sorting, weighting, DAOStarFinder, background noise, selection]
related: [StarAlignment, Integration, DynamicPSF, RadialProfileMeasurement]
icon: list-check
references:
  - "PixInsight — SubframeSelector process reference."
  - "photutils.detection.DAOStarFinder — DAOPHOT-like source detection."
  - "astropy.stats — sigma_clipped_stats, mad_std."
---

## Summary

`SubframeSelector` inspects a set of raw light frames and measures, for each one, objective
quality indicators: number of detected stars, apparent star size (FWHM), background noise
level, and a proxy signal-to-noise ratio. From these measurements it derives a **relative
weight** per frame, usable to sort, reject or weight subs before alignment (`StarAlignment`)
and stacking (`Integration`). This is a **read-only global** process: it creates no window and
never touches pixel data; results are exposed in `.measurements` (a list of dicts, one per
frame) after calling `measure()` (or `execute_global`, triggered via `app.run(...)`).

## Use cases

- **Sort a night's acquisition** before integration: spot blurry subs (passing cloud, focus
  drift, tracking failure) without opening each one in a viewer.
- **Reject unwanted frames** by filtering on `fwhm`, `stars` or `snr` before building the file
  list passed to `Integration`.
- **Weight an integration**: use `weight` as a per-frame weight in a weighted-stacking scheme
  rather than a plain average.
- **Audit a session**: produce a tabular report (median FWHM, noise, star count) to compare
  several nights or acquisition setups.

## How it works

For each path in `frames`, the image is loaded and converted to luminance (channel mean if the
image is color, single channel otherwise). Processing then chains:

1. **Robust background statistics** via `astropy.stats.sigma_clipped_stats` (sigma = 3): median
   and standard deviation of the sky background, insensitive to star peaks.
2. **Noise estimation** via `mad_std` (standard deviation derived from the median absolute
   deviation), computed independently of the median from the previous step.
3. **Star detection** with `photutils.detection.DAOStarFinder`, applied to the
   background-subtracted image (`luminance − median`), with an absolute detection threshold of
   `threshold_sigma × standard deviation` and a search scale given by `fwhm`.
4. **FWHM proxy**: DAOStarFinder does not fit a full Gaussian profile; the effective FWHM is
   therefore approximated from the returned `sharpness` column (median over sources) relative
   to the input `fwhm` parameter. When no source is detected, the `fwhm` parameter itself is
   used as a fallback.
5. **SNR proxy**: ratio of the background median to the robust standard deviation (`mad_std`) —
   a global background-to-noise contrast indicator, not a per-star signal-to-noise measurement.
6. **Relative weight**: a combination of star count, FWHM and noise, normalized so the weights
   of all frames sum to 1.

## Mathematics

Let $L$ be the luminance of a frame. Robust background statistics (median $\tilde{L}$ and
sigma-clipped standard deviation) are estimated by iterative $3\sigma$ rejection, then noise is
estimated independently as:

$$ \sigma = \operatorname{mad\_std}(L) = 1.4826 \cdot \operatorname{med}\!\big(|L - \operatorname{med}(L)|\big). $$

Star detection runs on the background-subtracted image, $L - \tilde{L}$, with an absolute
threshold:

$$ T = \texttt{threshold\_sigma} \times \sigma. $$

The star count $n$ is the number of sources returned by DAOStarFinder. The SNR proxy and
relative weight for frame $i$ (out of $N$) are:

$$ \mathrm{snr}_i = \frac{\tilde{L}_i}{\sigma_i}, \qquad
   w_i = \frac{\dfrac{n_i}{\mathrm{FWHM}_i \cdot \sigma_i}}
              {\displaystyle\sum_{j=1}^{N} \dfrac{n_j}{\mathrm{FWHM}_j \cdot \sigma_j}}. $$

This formula favors frames with **many stars**, **low FWHM** (good sharpness) and **low
noise** — consistent with the intuition that a good sub should be sharp, quiet, and rich in
detectable signal. If no frame is supplied, `raw.sum()` falls back to 1 to avoid a division by
zero.

## Parameters

- **`frames`** — *pathlist*, default `[]`. List of frame file paths to measure (raw light
  frames, typically before calibration/alignment).
- **`fwhm`** — *real*, default `3.0`, range `1.0`–`20.0`. Expected approximate star FWHM (in
  pixels), passed to `DAOStarFinder` as the detection scale and used as the fallback value for
  the FWHM proxy.
- **`threshold_sigma`** — *real*, default `5.0`, range `1.0`–`50.0`. Detection threshold
  expressed in multiples of the robust background standard deviation (`mad_std`); higher values
  count only stars clearly above the noise.

## Tips & pitfalls

> **Warning** — the returned FWHM is a **proxy**, derived heuristically from DAOStarFinder's
> "sharpness" and not an actual Gaussian fit of star profiles. For an accurate per-star FWHM
> (real PSF fit), use `DynamicPSF` or `RadialProfileMeasurement` instead.

> **Note** — the SNR proxy compares the background median to its noise; it is **not** the SNR
> of a star or the target object. Do not interpret it as a signal-depth measurement.

- A frame with no detected stars (cloud, extreme defocus) gets a weight of 0 in the formula:
  tune `threshold_sigma` or `fwhm` if otherwise usable subs are wrongly excluded.
- Compared frames should have comparable exposure/gain: median and noise are not normalized by
  exposure time.
- This process **creates no window**; consume `.measurements` from the console to filter the
  `frames` list before passing it to `StarAlignment`/`Integration`.

## See also

- [DynamicPSF](retina-doc://DynamicPSF) — per-star PSF profile fitting.
- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — star radial profile measurement.
- [StarAlignment](retina-doc://StarAlignment) — typical next step: aligning the retained frames.
- [Integration](retina-doc://Integration) — stacking, optionally weighted by `weight`.

## References

- PixInsight — *SubframeSelector* process reference.
- photutils.detection — *DAOStarFinder* (DAOPHOT-like source detection).
- astropy.stats — *sigma_clipped_stats*, *mad_std*.
