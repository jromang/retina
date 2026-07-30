---
id: SpectrophotometricFluxCalibration
category: ColorCalibration
title: Spectrophotometric Flux Calibration
brief: "Flux calibration: derives an instrument-to-physical zero point from Gaia (G magnitude)."
keywords: [flux, photometry, zero point, Gaia, WCS, calibration, magnitude]
related: [SpectrophotometricColorCalibration, PhotometricColorCalibration, PlateSolve, SourceExtraction]
icon: prism
references:
  - "Gaia DR3 — phot_g_mean_mag and the Gaia photometric system."
  - "photutils.aperture — aperture_photometry, CircularAperture."
  - "PixInsight — SpectrophotometricColorCalibration (flux calibration mode)."
---

## Summary

`SpectrophotometricFluxCalibration` establishes a **zero point** relating the instrumental flux
(counted in normalized pixel/ADU units) to the true physical flux of stars, using the **Gaia
DR3** catalog and its **G magnitude**. Unlike `PhotometricColorCalibration` and
`SpectrophotometricColorCalibration`, which correct **color balance** (per-channel R/G/B gains),
this process only derives a single **global scale factor** (`zero_point`): it does not change
hues, only the radiometric scale. It is a building block for making intensity measurements
**comparable across sessions**, instruments, or observing nights.

## Use cases

- **Measure a flux calibration zero point** without altering the image (default mode,
  `apply = False`) — useful to characterize a sensor/setup or document a session.
- **Compare absolute intensities** between several images of the same target taken on different
  dates, once each has been brought back to the same physical scale.
- **Prepare a photometric measurement** (variables, novae, comets) ahead of quantitative
  analysis, ensuring measured fluxes are physically consistent with Gaia.
- **Diagnose exposure/gain drift** between sessions by comparing successive `zero_point` values.

## How it works

The process requires a view whose window carries a valid **WCS** (obtained via `PlateSolve`):

1. **Query the Gaia catalog** (`astroquery.gaia`) around the image center, over a radius derived
   from the field, filtered on a G-magnitude range (`mag_bright`–`mag_faint`) — or use a catalog
   supplied explicitly via `set_catalog(...)` for headless/offline use.
2. **Project** the catalog (RA, Dec) positions onto pixel coordinates through the WCS
   (`world_to_pixel_values`), discarding stars too close to the field edges (margin =
   `aperture_radius`).
3. **Aperture photometry** (`photutils.aperture.CircularAperture` + `aperture_photometry`) on
   the **luminance channel** — the G (green) channel for color images, otherwise the single
   channel — after subtracting a robust sky background (`sigma_clipped_stats`, 3σ median).
4. For each retained star, compute the **expected physical flux** from its Gaia G magnitude:
   $\phi_{\text{phys}} \propto 10^{-0.4\,G}$.
5. The **zero point** is the **median** (outlier-resistant) of the ratio physical flux /
   measured flux over all valid stars (strictly positive measured flux).
6. In `apply = True` mode, the image is multiplied by this zero point then **renormalized** by
   its maximum to stay displayable in `[0, 1]`; in measurement mode (`apply = False`), only
   `zero_point` and `n_stars` are set on the instance, with no image change and no history entry
   pushed.

## Mathematics

Let $\{(\phi_i, G_i)\}_{i=1}^{N}$ be the set of valid catalog stars in the field, where $\phi_i$
is the measured instrumental flux (aperture photometry, background-subtracted) and $G_i$ their
Gaia magnitude. The expected physical flux follows the magnitude/flux relation:

$$ \phi_i^{\text{phys}} = 10^{-0.4\, G_i}. $$

The zero point $Z$ is estimated as the **median of the individual ratios**, which makes it
resistant to poorly measured stars (saturation, contamination, crowding) without requiring an
explicit sigma-rejection pass:

$$ Z = \operatorname{med}_i \left( \frac{\phi_i^{\text{phys}}}{\phi_i} \right), \qquad
   i \in \{\, i : \phi_i > 0 \,\}. $$

In `apply` mode, the image $I$ is rescaled and then renormalized by its maximum
$M = \max(Z \cdot I)$ to remain displayable:

$$ I' = \operatorname{clip}\!\left( \frac{Z \cdot I}{M},\; 0,\; 1 \right). $$

This max-renormalization preserves the **relative ratio** between pixels (hence internal
photometric consistency within the image) while keeping values in the standard floating-point
display range — the true zero point $Z$ remains available via the instance's `zero_point`
attribute for any subsequent quantitative computation.

## Parameters

- **`mag_bright`** — *real*, default `7.0`, range `-5.0`–`20.0`. Brightest accepted Gaia G
  magnitude; excludes the most luminous stars, which are likely saturated or non-linear in the
  image.
- **`mag_faint`** — *real*, default `13.0`, range `0.0`–`22.0`. Faintest accepted Gaia G
  magnitude; bounds the minimum signal-to-noise ratio of the stars used for the measurement.
- **`aperture_radius`** — *real*, default `5.0`, range `1.0`–`50.0`. Radius (pixels) of the
  circular photometry aperture; should cover most of the PSF flux without pulling in too much
  background or neighboring stars.
- **`max_stars`** — *int*, default `300`, range `3`–`5000`. Maximum number of stars requested
  from the Gaia query (`TOP` limit of the ADQL query).
- **`apply`** — *bool*, default `False`. If `False` (default), the process only **measures** the
  zero point (`zero_point`, `n_stars`) without modifying the image or pushing a history entry.
  If `True`, the image is actually rescaled and renormalized.

## Tips & pitfalls

> **Warning** — a WCS is **mandatory**: run `PlateSolve` before this process. Without a valid
> WCS (`window.wcs is None`), a `ValueError` is raised immediately.

> **Note** — the default mode (`apply = False`) never modifies the image: it is a pure
> measurement. Inspect `instance.zero_point` and `instance.n_stars` after execution rather than
> relying on a visible change.

- The zero point depends on the **input scale** of the image (preferably linear, unstretched):
  running this process after a non-linear stretch (`HistogramTransformation`,
  `CurvesTransformation`) invalidates the flux/magnitude relation.
- Too few valid stars (fewer than 3 in the field after edge filtering, or fewer than 3 with
  positive measured flux) raises an explicit error — widen `mag_bright`/`mag_faint` or check the
  aperture radius.
- For **offline** use (no network access to Gaia), supply a local catalog via
  `set_catalog([(ra, dec, bp, g, rp), …])` before calling `execute_on`.
- This process **does not correct color**: for photometric white balance, use
  `PhotometricColorCalibration` or `SpectrophotometricColorCalibration` alongside it.

## See also

- [SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration) — color
  balance via Gaia synthetic photometry (per-channel gains, same measurement infrastructure).
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — simple color balance
  (direct RP/G/BP → R/G/B mapping).
- [PlateSolve](retina-doc://PlateSolve) — mandatory prerequisite step (provides the WCS).
- [SourceExtraction](retina-doc://SourceExtraction) — source detection, useful to visually
  validate the field before photometric calibration.

## References

- Gaia DR3 — *phot_g_mean_mag* and the Gaia photometric system.
- photutils.aperture — *aperture_photometry*, *CircularAperture*.
- PixInsight — *SpectrophotometricColorCalibration* (flux calibration mode).
