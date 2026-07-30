---
id: SurveyReference
category: BackgroundModelization
title: Survey Reference
brief: Synthesises a gradient-free reference image of the field from an all-sky survey (HiPS / hips2fits).
keywords: [survey, HiPS, hips2fits, DSS2, Pan-STARRS, gradient, sky background, reference, CDS, MARS]
related: [MultiscaleGradientCorrection, PlateSolve, GradientCorrection, BackgroundExtraction]
icon: stars
references:
  - "Fernique, P. et al. — HiPS: Hierarchical Progressive Survey (IVOA Recommendation)."
  - "CDS Strasbourg — hips2fits service: https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
  - "Second Palomar Observatory Sky Survey (POSS-II) / Digitized Sky Survey — STScI / AURA."
---

## Summary

`SurveyReference` builds a **gradient-free image of the very field you are working on**,
taken from an all-sky survey, and opens it as a new window. Because the survey image is
observed from a different site, on a different night, through different optics, it does not
share your gradient — but it does share the *shape* of the real sky. That is exactly what
`MultiscaleGradientCorrection` needs to tell an actual nebulosity apart from light pollution.

The process is **global**: it does not touch the pixels of the source window. It requires an
**astrometric solution** on that window (`PlateSolve`, or a file that already carries its
WCS — Retina reads it when opening).

## Use cases

- Correct a light-pollution gradient **without eroding extended nebulosity**, IFN, or the
  outer halo of a galaxy — the failure mode of every reference-free background extraction.
- Check that a suspicious large-scale structure in your integration is **real** rather than a
  calibration artefact: if it is in the survey too, it is in the sky.
- Get a quick visual identification of the field (nearby galaxies, dust lanes) at the same
  scale and orientation as your image, thanks to the shared WCS.

## How it works

The window's WCS is **sub-sampled** to at most `max_size` pixels on its longest side, keeping
the exact same sky footprint. That reduced WCS is sent to the CDS **`hips2fits`** service,
which renders the chosen HiPS survey directly onto that grid and returns a FITS image — so
there is no survey database to download and no reprojection to perform locally.

The returned plate is normalised into `[0, 1]` by robust percentiles and opened as a new
window carrying the reduced WCS, so it lines up with the source (linked views, celestial
readout). The result is cached on disk under the user cache directory, keyed by survey and
sky grid: adjusting the correction ten times costs one network request.

## Parameters

- **`view_id`** — *str*, default empty. Source window (empty = the active one). Its
  astrometric solution defines the field to fetch.
- **`survey`** — *enum*, default `dss2-red`. The sky survey:
  - `dss2-red`, `dss2-blue` — Digitized Sky Survey 2. **Full sky coverage**, which is why
    red is the default.
  - `panstarrs-g`, `panstarrs-r`, `panstarrs-i` — Pan-STARRS DR1: deeper and better sampled,
    but nothing below declination ≈ −30°.
  - `halpha` — full-sky H-alpha map (Finkbeiner), the only meaningful reference for a
    narrowband frame, where a broadband continuum says nothing about your signal.
  - `custom` — any HiPS id from the CDS registry, given in `hips_id`.
- **`hips_id`** — *str*, only with `survey = custom`. E.g. `CDS/P/AllWISE/W1`.
- **`max_size`** — *int*, default `1024`, `0` = full resolution. Longest side of the
  requested reference.
- **`use_cache`** — *bool*, default `true`. Reuse a previously fetched reference for the
  same survey and field.
- **`new_image_id`** — *str*, default empty (`<source>_<survey>`).

## Tips & pitfalls

> **Warning** — only HiPS surveys stored as **FITS tiles** can be rendered as FITS. The
> best-known survey id, `CDS/P/DSS2/color`, is stored as JPEG: it would return 8-bit,
> already-stretched data, useless for measuring a background. The presets above are all
> FITS-backed; if you use `custom`, check that the survey is too.

> **Note** — a survey plate is **neither linear nor photometric**. Nothing here is
> calibrated, and nothing needs to be: `MultiscaleGradientCorrection` fits an affine
> relation per channel, which absorbs any scale and offset. Do not use this image for
> photometry.

- `max_size` does not need to be large. Only the large scales are ever consumed, so a
  reference around 1024 px is plenty even for a 50-megapixel integration — and it keeps
  requests fast and the cache small.
- If the survey does not cover your field (Pan-STARRS in the far south), the process says so
  explicitly instead of returning an image full of holes.
- The reference is a normal window: look at it, blink it against your image, and only then
  correct.

## Console

```python
app.open("/data/M31/integration.fits")     # a solved file already carries its WCS
SurveyReference(survey="dss2-red").execute_global(app)
MultiscaleGradientCorrection(reference="M31_dss2-red").execute_on(app.active_view)
```

## See also

- [MultiscaleGradientCorrection](retina-doc://MultiscaleGradientCorrection) — the consumer
  of this reference.
- [PlateSolve](retina-doc://PlateSolve) — obtain the astrometric solution this process
  requires.
- [GradientCorrection](retina-doc://GradientCorrection) — polynomial gradient removal, with
  no external data.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — tile-grid background model.

## References

- Fernique, P. et al. — *HiPS: Hierarchical Progressive Survey* (IVOA Recommendation).
- CDS Strasbourg — `hips2fits` service.
- Digitized Sky Survey — STScI / AURA; Pan-STARRS1 Surveys — Chambers, K. C. et al.
