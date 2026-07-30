---
id: AperturePhotometry
category: ImageInspection
title: Aperture Photometry
brief: Measures flux, uncertainty and magnitude of detected sources, with an annulus background.
keywords: [photometry, aperture, annulus, flux, magnitude, SNR, CSV, light curve]
related: [SourceExtraction, NoiseEvaluation, PhotometricColorCalibration, DynamicPSF]
icon: circle
references:
  - "photutils.aperture — CircularAperture, CircularAnnulus, ApertureStats."
  - "PixInsight — AperturePhotometry script."
---

## Summary

`AperturePhotometry` detects sources, measures each one's flux in a **circular aperture**,
subtracts a background taken from an **annulus** around it, and returns a table: position,
flux, uncertainty, signal-to-noise ratio, instrumental magnitude — and celestial coordinates if
the field is plate-solved.

## The annulus is not a detail

Subtracting a **global** background amounts to assuming the sky is flat. It never is: light
pollution gradient, halo of a bright star, nebulosity. The annulus measures the sky *where the
source is*, and its **median** rejects the neighbours that wander into it.

On the test field — twelve sources of known flux laid on a background gradient — measurement
recovers the true fluxes to within **2%**. Without an annulus, the error would track the
gradient.

A source whose annulus **falls off the frame** is discarded: keeping it would return a flux
computed against a partial background, wrong without saying so.

## Use cases

- **Light curves**: measure a variable frame after frame, export, plot elsewhere.
- **Quality control**: the signal-to-noise ratio of a frame's stars, compared night to night.
- **Check a flux calibration** or a zero point.

## What the uncertainty is worth, and is not

It assumes **Gaussian** noise of dispersion measured on the annulus, integrated over the
aperture area, plus the uncertainty on the background itself. It does **not** assume photon
noise: our images are normalized, and the gain that would let us count electrons is unknown to
the process.

So it is a *relative* uncertainty: good for comparing sources with each other, or one source
across frames, not for publishing an absolute magnitude.

## Export is a domain gesture

A table you cannot get out is only there to be looked at. `output_path` writes the CSV from the
domain — hence from the console, hence from a script — and an interface button will never do
more than fill that parameter. This is the project's parity rule: if export existed only in a
panel, it would be a GUI capability, which Retina forbids itself.

Columns are `id, x, y, ra, dec, flux, flux_error, snr, magnitude, background, aperture_area`.

## Parameters

- **`fwhm`** — *real*, default `3.0`. Approximate FWHM for detection.
- **`threshold_sigma`** — *real*, default `5.0`. Detection threshold in background σ.
- **`max_sources`** — *int*, default `500`. Brightest first.
- **`aperture_radius`** — *real*, default `5.0`. Aperture radius, in pixels. A good value is
  around 1.5 to 2 FWHM: too small and you lose flux; too large and you pick up neighbours.
- **`annulus_inner`** / **`annulus_outer`** — *real*, defaults `8.0` / `12.0`. The background
  annulus. The inner radius must clear the aperture by a margin, or it still measures the star.
- **`channel`** — *int*, default `-1`. Channel measured; `-1` uses luminance.
- **`zero_point`** — *real*, default `0.0`. Additive magnitude constant.
- **`output_path`** — *path*. If set, the CSV is written at the end of the measurement.
- **`show_apertures`** — *bool*, default `False`. Draw apertures in the viewport.

Read-only; result in `.result`.

## Tips & pitfalls

> **Saturated stars corrupt everything.** Their flux is clipped, hence underestimated, and
> nothing in the measurement flags it. Raise `threshold_sigma` or discard them on reading.

- Measure on **linear** data. After stretching, flux is no longer proportional to photon count
  and a magnitude means nothing.
- Check `aperture_area`: on a dense field, two overlapping apertures count the same pixels
  twice.

## See also

- [SourceExtraction](retina-doc://SourceExtraction) — detection alone, with segmentation and
  deblending.
- [NoiseEvaluation](retina-doc://NoiseEvaluation) — the image's noise, measured properly.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — the same photometry,
  in the service of colour.

## References

- photutils.aperture — *CircularAperture*, *CircularAnnulus*, *ApertureStats*.
- PixInsight — *AperturePhotometry* script.
