---
id: PhotometricColorCalibration
category: ColorCalibration
title: Photometric Color Calibration
brief: Astrometric white balance via aperture photometry of Gaia stars (≈ PixInsight's SPCC).
keywords: [white balance, Gaia, photometry, WCS, plate solve, color, calibration]
related: [SpectrophotometricColorCalibration, PlateSolve, ColorCalibration, BackgroundNeutralization]
icon: palette
references:
  - "PixInsight — PhotometricColorCalibration (PCC) / SpectrophotometricColorCalibration (SPCC) tool reference."
  - "Gaia DR3 — phot_bp_mean_mag, phot_g_mean_mag, phot_rp_mean_mag (Gaia Archive, gaiadr3.gaia_source)."
  - "photutils.aperture — CircularAperture, aperture_photometry."
  - "astropy.stats — sigma_clipped_stats."
---

## Summary

`PhotometricColorCalibration` (PCC) derives an **objective white balance**, anchored to the
**Gaia DR3** star catalog, instead of a visual adjustment. The principle: measure the
instrumental flux of the field's stars in each R/G/B channel, compare it to the flux they should
have according to their Gaia catalog magnitudes (BP/G/RP), and derive a **per-channel gain**
that aligns the image's stellar colors with photometric reality. This is an approximate
equivalent of PixInsight's PCC/SPCC. The process requires a **color** image carrying a valid
**WCS** (obtained via `PlateSolve`).

## Use cases

- **Correct the white balance** of an RGB or LRGB image reproducibly, without relying on visual
  judgment or a manually chosen reference star.
- **Compare sessions** acquired with different filters, sensors, or conditions by bringing them
  back to a common colorimetric reference (Gaia).
- **Diagnose a color cast** (thin cloud, unbalanced filter, residual IR/UV) by inspecting the
  returned gains (`gains`) without necessarily applying them (`apply=False`).
- **Validate an RGB workflow** at the end of a pipeline — after calibration, integration,
  registration, and gradient removal — before the final stretch.

## How it works

1. **Catalog** — the process queries the Gaia service (`astroquery.gaia`) around the field
   center (derived from the window's WCS), within an angular radius capped at 2°, filtering
   stars whose G magnitude falls in `[mag_bright, mag_faint]` and whose BP/RP are populated. A
   catalog can also be supplied explicitly in headless mode via `set_catalog(...)`, to avoid
   network access (tests, offline environments).
2. **Projection** — each star's celestial coordinates (RA/Dec) are projected to image pixels
   through the WCS (`world_to_pixel_values`); only stars farther than `aperture_radius` from the
   edges are kept.
3. **Aperture photometry** — for each channel, the local sky background is estimated via robust
   statistics (sigma-clipped median, `sigma_clipped_stats`) and subtracted, then each star's flux
   is integrated within a circular aperture of radius `aperture_radius`
   (`photutils.aperture.CircularAperture` / `aperture_photometry`).
4. **Catalog flux** — Gaia magnitudes are converted to flux via $10^{-0.4\,m}$, with the
   simplified mapping **RP→R, G→G, BP→B** (an approximation of a true SPCC, which would use
   filter+sensor response curves and synthetic spectra rather than a 1:1 band mapping).
5. **Gains** — for each valid star (positive measured flux and finite catalog flux), the ratio
   catalog-flux/measured-flux is formed per channel; the final per-channel gain is the **median**
   of these ratios across all stars (robust against poorly measured, double, or saturated stars).
   Gains are then normalized by the G-channel gain, used as the reference.
6. **Application** — if `apply=True`, each channel is multiplied by its gain and the image is
   clipped to `[0, 1]`; otherwise only `gains` and `n_stars` are computed (measure-only mode).

## Mathematics

For a star $i$ with Gaia magnitudes $(m_i^{BP}, m_i^G, m_i^{RP})$, the per-channel catalog flux
follows from the magnitude-flux relation:

$$ f_i^{R} = 10^{-0.4\,m_i^{RP}}, \qquad f_i^{G} = 10^{-0.4\,m_i^{G}}, \qquad f_i^{B} = 10^{-0.4\,m_i^{BP}}. $$

The measured instrumental flux $\hat{f}_i^{c}$ in channel $c$ is the aperture photometry after
subtracting the local background $\mu_c$:

$$ \hat{f}_i^{c} = \sum_{(x,y) \,\in\, A(x_i, y_i, r)} \big( I_c(x,y) - \mu_c \big), $$

where $A(x_i, y_i, r)$ is the aperture disk of radius $r = $ `aperture_radius` centered on the
star's pixel projection $(x_i, y_i)$, and $\mu_c$ the background level estimated by sigma-clipped
median over the whole channel. The raw per-channel gain is the median, over the $N$ valid stars,
of the catalog-to-measured flux ratio:

$$ g_c = \operatorname{med}_i \left( \frac{f_i^{c}}{\hat{f}_i^{c}} \right), $$

then normalized by the green channel, taken as the white-balance reference:

$$ g_c \leftarrow \frac{g_c}{g_G}. $$

The corrected image is finally:

$$ I_c'(x,y) = \operatorname{clip}\big(g_c \cdot I_c(x,y),\; 0,\; 1\big), \qquad c \in \{R, G, B\}. $$

Using the **median** rather than the mean makes the estimate robust against double, saturated,
or poorly centered stars, which would otherwise produce outlier ratios.

## Parameters

- **`mag_bright`** — *real*, default `7.0`, range `-5`–`20`. Brightest accepted Gaia G magnitude.
  Too low lets through stars close to sensor saturation, which corrupts their measured flux.
- **`mag_faint`** — *real*, default `13.0`, range `0`–`22`. Faintest accepted Gaia G magnitude.
  Too high includes noisy stars close to the sky background, whose photometry is unreliable.
- **`aperture_radius`** — *real*, default `5.0`, range `1`–`50` (pixels). Radius of the
  photometry aperture disk. Should cover most of the stars' profile (PSF/FWHM) without
  encroaching on neighboring stars.
- **`max_stars`** — *int*, default `300`, range `3`–`5000`. Maximum number of stars requested
  from Gaia (the `TOP` limit of the ADQL query). More stars stabilizes the median but lengthens
  the network query.
- **`apply`** — *bool*, default `True`. If true, applies the gains to the image (destructive
  operation, recorded in history); if false, only measures and populates `gains`/`n_stars`
  without touching pixels or pushing a history entry.

## Tips & pitfalls

> **Warning** — the process explicitly fails if the window has no WCS (run `PlateSolve` first)
> or if the image has fewer than 3 color channels.

> **Note** — the Gaia BP/G/RP ≈ broad B/G/R bands approximation is coarser than PixInsight's
> true SPCC, which integrates synthetic spectra over the actual filter+sensor response. For a
> more faithful result on non-standard broad filters, prefer
> `SpectrophotometricColorCalibration`, which combines Gaia fluxes through nominal passbands.

- In headless mode or without network access, inject a catalog via
  `set_catalog([(ra, dec, bp, g, rp), …])` to avoid the `astroquery.gaia` request.
- If fewer than 3 catalog stars fall within the field, or fewer than 3 are measurable (positive
  flux), the process raises an error: widen `mag_faint` or check the WCS.
- Run first with `apply=False` to inspect `gains` and `n_stars` before applying, especially on a
  field poor in cataloged stars.
- Gradient removal (`BackgroundExtraction`/`BackgroundNeutralization`) should precede PCC: a
  poorly subtracted background biases the per-channel local sky-level estimate.

## See also

- [SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration) — more
  faithful variant, synthesizing R/G/B channels via passbands combining Gaia BP/G/RP fluxes.
- [PlateSolve](retina-doc://PlateSolve) — required prerequisite step (provides the WCS).
- [ColorCalibration](retina-doc://ColorCalibration) — catalog-free white balance (local reference).
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — neutralizes the sky background before color calibration.

## References

- PixInsight — *PhotometricColorCalibration (PCC)* / *SpectrophotometricColorCalibration (SPCC)* tool reference.
- Gaia DR3 — `phot_bp_mean_mag`, `phot_g_mean_mag`, `phot_rp_mean_mag` (Gaia Archive, `gaiadr3.gaia_source`).
- photutils.aperture — *CircularAperture*, *aperture_photometry*.
- astropy.stats — *sigma_clipped_stats*.
