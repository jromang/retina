---
id: SpectrophotometricColorCalibration
category: ColorCalibration
title: Spectrophotometric Color Calibration (SPCC)
brief: White balance by synthetic photometry on real Gaia spectra and your instrument's measured response.
keywords: [SPCC, colour calibration, Gaia, XP spectra, synthetic photometry, white balance, WCS, filters, narrowband]
related: [FilterManager, PhotometricColorCalibration, PlateSolve, BackgroundNeutralization, ColorCalibration]
icon: palette
references:
  - "PixInsight — SpectrophotometricColorCalibration tool reference."
  - "Gaia DR3 — G, BP, RP photometric bands (Gaia Collaboration, 2022)."
  - "photutils.aperture — CircularAperture / aperture_photometry."
---

## Summary

`SpectrophotometricColorCalibration` (SPCC) computes a **white balance from stellar
photometry**. The reasoning fits in one sentence: for every star in the field we know what the
instrument *should* have measured — its spectrum integrated over each channel's response — and
we compare that with what it did measure. The ratio gives the channel gain.

That requires real spectra and real curves. Retina uses the **Gaia DR3 sampled spectra**
(`spectrum_source = gaia_xp`), which carry each star's reddening and metallicity, and a
**curve database** of filter transmissions and sensor quantum efficiencies (see
[FilterManager](retina-doc://FilterManager)). The **white reference** then fixes what is
declared neutral.

As long as no curve is named, the process explicitly falls back to **nominal passbands**
applied to the three Gaia magnitudes — the original behaviour. That is deliberate: three
channels with no curve would share the same response, and SPCC would become a silent no-op.

The process requires a **WCS** (from `PlateSolve`) and a **colour** image.

## Use cases

- **Calibrate the color** of an RGB image before final stretching, to obtain star colors
  and hues consistent with an objective photometric standard (Gaia) rather than a purely
  visual balance.
- **Replace a manual `ColorCalibration`** with a catalog-anchored method, useful when the
  field contains enough non-saturated cataloged stars.
- **Check color consistency** across sessions/optics: the resulting
  `SpectrophotometricColorCalibration.gains` are a useful diagnostic even without applying
  the correction (`apply=False`).
- **LRGB/narrowband pipeline**: run on the final color composite, after alignment and before
  the non-linear stretch.

## How it works

1. **Catalog retrieval**: if no catalog was injected via
   `set_catalog([(ra, dec, bp, g, rp), …])`, the process queries Gaia DR3 online
   (`astroquery.gaia`) within a radius centered on the field (capped at 2°), filtering stars
   whose G magnitude falls between `mag_bright` and `mag_faint` and that have valid BP and
   RP magnitudes. The star count is capped at `max_stars`.
2. **WCS projection**: catalog celestial coordinates (ra, dec) are converted to pixel
   coordinates via the window's WCS (`win.wcs.world_to_pixel_values`); only stars landing in
   the field, at least `aperture_radius` from the edges, are kept.
3. **Instrumental aperture photometry**: for each channel R, G, B, the sky background is
   estimated with sigma-clipped robust statistics (`astropy.stats.sigma_clipped_stats`) and
   subtracted, then each star's flux is integrated over a circular aperture of radius
   `aperture_radius` (`photutils.aperture.CircularAperture` / `aperture_photometry`).
4. **Synthetic catalog flux**: Gaia magnitudes (BP, G, RP) are converted to flux
   ($10^{-0.4\,m}$), then each channel's synthetic flux (R, G, B) is obtained as a linear
   combination of the three Gaia fluxes through a fixed **nominal passband** matrix
   (inter-band overlap), rather than a 1:1 mapping as in PCC.
5. **Gain computation**: the catalog-flux / measured-flux ratio is computed per star and per
   channel; the **median** of these ratios gives an outlier-robust gain, which is then
   normalized by the G channel's gain (white-balance reference).
6. **Application**: if `apply=True`, each channel is multiplied by its gain and the result
   is clipped to `[0, 1]`; otherwise only the measurement is performed (gains remain
   accessible on the instance, no history entry is created).

## Mathematics

For each catalog star $i$ falling in the field, its Gaia magnitudes
$(m_{BP,i}, m_{G,i}, m_{RP,i})$ are converted to catalog flux:

$$ f_{RP,i} = 10^{-0.4\,m_{RP,i}}, \qquad f_{G,i} = 10^{-0.4\,m_{G,i}}, \qquad
   f_{BP,i} = 10^{-0.4\,m_{BP,i}}. $$

The **synthetic per-channel instrument flux** $c \in \{R, G, B\}$ is obtained through a
nominal passband matrix $\mathbf{P}$ (each row sums to 1) applied to
$(f_{RP,i}, f_{G,i}, f_{BP,i})$:

$$ \begin{pmatrix} f^{\text{synth}}_{R,i} \\ f^{\text{synth}}_{G,i} \\ f^{\text{synth}}_{B,i}
   \end{pmatrix}
   = \mathbf{P} \begin{pmatrix} f_{RP,i} \\ f_{G,i} \\ f_{BP,i} \end{pmatrix}, \qquad
   \mathbf{P} = \begin{pmatrix} 0.85 & 0.10 & 0.05 \\ 0.10 & 0.80 & 0.10 \\
   0.05 & 0.10 & 0.85 \end{pmatrix}. $$

Row $R$ is dominated by RP (0.85), row $B$ by BP (0.85), and row $G$ by G (0.80) — with 10 to
15% cross-contamination modeling the overlap of Gaia's passbands. On the image side, the
measured instrumental flux $f^{\text{mes}}_{c,i}$ is the sum of aperture pixels after
subtracting the local background $\tilde{b}_c$:

$$ f^{\text{mes}}_{c,i} = \sum_{(x,y)\,\in\,\text{aperture}_i} \big(I_c(x,y) - \tilde{b}_c\big). $$

The channel gain is the **robust median** of the catalog-flux/measured-flux ratio over all
valid stars $\mathcal{V}$ (positive measured flux, finite synthetic flux):

$$ g_c = \operatorname{med}_{i \in \mathcal{V}} \left( \frac{f^{\text{synth}}_{c,i}}
   {f^{\text{mes}}_{c,i}} \right), \qquad g_c \leftarrow \frac{g_c}{g_G}. $$

Normalizing by $g_G$ fixes the green channel as the reference (white balance without
changing overall luminance). The corrected image is then:

$$ I'_c(x,y) = \operatorname{clip}\big(g_c \, I_c(x,y),\; 0,\; 1\big). $$

Using the median rather than the mean makes the estimate robust to double stars, saturated
stars, or poorly centered ones that would bias a plain average ratio.

## Parameters

- **`mag_bright`** — *real*, default `7.0`, range `-5`–`20`. Brightest Gaia G magnitude kept
  from the catalog; excludes the brightest stars, which are often saturated in the image and
  therefore bias aperture photometry.
- **`mag_faint`** — *real*, default `13.0`, range `0`–`22`. Faintest Gaia G magnitude kept;
  beyond it, stellar signal-to-noise becomes too low for a reliable measurement.
- **`aperture_radius`** — *real*, default `5.0`, range `1`–`50`. Radius (pixels) of the
  circular photometry aperture. Should be tuned to the image's star FWHM (too small =
  underestimated flux, too large = contamination from neighboring stars).
- **`max_stars`** — *int*, default `300`, range `3`–`5000`. Maximum number of stars queried
  from the Gaia catalog (bounds the `TOP N` query and computation time).
- **`apply`** — *bool*, default `True`. If true, applies the gains to the image (destructive
  operation, history entry). If false, only performs the measurement: gains remain readable
  on `process.gains` without modifying the image.

### Instrument response

- **`spectrum_source`** — *enum* `gaia_xp` | `gaia_photometry`, default `gaia_xp`. Sampled
  spectra, or the three magnitudes alone.
- **`red_filter`**, **`green_filter`**, **`blue_filter`** — *str*, empty by default.
  Transmission curve identifiers (`FilterManager(action='list', kind='filter')`).
- **`red_sensor`**, **`green_sensor`**, **`blue_sensor`** — *str*, empty by default. Quantum
  efficiency curves. A colour sensor has one per channel; a mono sensor has one, repeated
  across the three.
- **`white_reference`** — *str*, default `average_spiral_galaxy`. The spectrum declared
  neutral. Empty means a flat spectrum.

### Narrowband

- **`narrowband`** — *bool*, default `False`. Replaces filter curves with rectangular
  passbands.
- **`red_wavelength`** / **`red_bandwidth`** (defaults `656.3` / `7.0` nm, i.e. Hα),
  **`green_wavelength`** / **`green_bandwidth`** and **`blue_wavelength`** /
  **`blue_bandwidth`** (defaults `500.7` nm, i.e. OIII) — *real*, in nanometres.

## Tips & pitfalls

> **Warning** — SPCC requires a **valid WCS** on the window (run `PlateSolve` first) and a
> **color** image with at least 3 channels; otherwise the process raises an explicit
> exception rather than silently producing a wrong result.

> **Note** — the passbands used are **fixed nominal coefficients**, not response curves
> measured for your sensor/filters. This is an approximation: the spectrophotometric
> accuracy remains lower than PixInsight's real SPCC, which integrates synthetic spectra
> over the actual sensor and filter response.

- Exclude saturated stars first (a high enough `mag_bright`): a clipped instrumental flux
  skews all the gains, not just the saturated channel's.
- Without network access, or for a reproducible test, use `set_catalog(...)` to supply an
  already-downloaded or synthetic Gaia catalog.
- A field too poor in stars (fewer than 3 valid after filtering) makes the computation fail:
  widen `mag_faint` or check the catalog search radius.
- Run `BackgroundNeutralization` beforehand if the sky background has a strong color cast:
  SPCC corrects **star** colors, not the background gradient.

## See also

- [FilterManager](retina-doc://FilterManager) — inspect and extend the curve database.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — variant with a
  1:1 mapping RP→R/G→G/BP→B, without combined passbands.
- [PlateSolve](retina-doc://PlateSolve) — prior astrometric solving, required for the WCS.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — colorimetric sky
  background neutralization, complementary.
- [ColorCalibration](retina-doc://ColorCalibration) — generic color calibration
  (catalog-free).

## References

- PixInsight — *SpectrophotometricColorCalibration* tool reference.
- Gaia DR3 — G, BP, RP photometric bands (Gaia Collaboration, 2022).
- photutils.aperture — *CircularAperture* / *aperture_photometry*.
