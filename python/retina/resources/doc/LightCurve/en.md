---
id: LightCurve
category: ImageInspection
title: Light Curve
brief: Differential photometry of a target across a series of frames, exportable in AAVSO format.
keywords: [light curve, photometry, variable star, exoplanet, differential, AAVSO, time series, JD]
related: [AperturePhotometry, SubframeSelector, ConeSearch, PlateSolve]
icon: chart-line
references:
  - "AAVSO — Extended File Format specification (https://www.aavso.org/aavso-extended-file-format)."
  - "Howell, S. B. — Handbook of CCD Astronomy, ch. 5 (aperture photometry, differential techniques)."
---

## Summary

`LightCurve` measures the brightness of one target across a whole series of frames and
turns it into a curve you can plot, export, and submit. It is the process behind variable
star work and exoplanet transits — the area where Siril has been ahead of everyone,
PixInsight included.

The process is **global**: it reads a list of files and never touches an open view.

## Use cases

- Follow an **eclipsing binary** or a pulsating variable through a night, and send the
  result to the AAVSO.
- Detect an **exoplanet transit** — a few millimagnitudes over a few hours, which only
  differential photometry can reach from the ground.
- Check that a **suspected variable** really varies, by comparing it against a check star
  measured the same way.

## How it works

Every frame is measured at the same sky positions: circular aperture, background taken in a
local annulus (the same core as
[AperturePhotometry](retina-doc://AperturePhotometry), shared so the two can never drift
apart).

Positions are carried from frame to frame by one of two routes, tried in order:

1. the **WCS in the frame header**, when there is one (registered pipeline outputs carry it);
2. otherwise, **star pattern matching** against the first frame (`astroalign`).

In both cases the predicted position is then **recentred** on the local centroid. That
recentring, not the accuracy of the WCS, is what makes the run trustworthy: an aperture off
by two pixels loses flux, and loses a *varying* amount of it from frame to frame — which
fabricates variability that is not there.

Each frame is timestamped from `DATE-OBS` plus **half the exposure**: a light curve dates an
integrated flux, and using the start would shift every point by half an exposure.

## Measure once, judge freely

Measuring is expensive, judging is free — the same split as
[SubframeSelector](retina-doc://SubframeSelector). `measure_raw()` does the photometry and
caches it **per file**; `evaluate()` derives the magnitudes in microseconds. Changing the
photometry mode, re-exporting, or adding one night to an existing series therefore costs
nothing on the frames already measured.

## Photometry modes

- **`ensemble`** (default) — the target is compared against the **summed** flux of all
  comparison stars. Summing amounts to a flux-weighted mean: a faint comparison carries
  little weight, and a comparison that turns out to be variable contaminates the result
  proportionally less.
- **`single`** — against the first comparison only. Useful when only one suitable star is in
  the field.
- **`instrumental`** — raw magnitude of the target, uncorrected. Diagnostic only: it tracks
  sky transparency, airmass and dew on the corrector far more than it tracks the star.

If **every** comparison carries a catalogue magnitude (the third value in its designation),
the output is shifted onto the standard scale and the AAVSO export declares `MTYPE=STD`;
otherwise it stays differential and declares `DIF`. Claiming a standard magnitude without a
catalogue reference would be a false declaration, so the process never does it silently.

## Designating stars

Two syntaxes, separated by `;`:

- `ra,dec` or `ra,dec,mag` — degrees. This is what an AAVSO chart gives you, and it survives
  field rotation.
- `x:y` — pixels **of the first frame**, for a series with no astrometric solution.

From the console, `set_stars()` is easier and writes the same parameters:

```python
curve = LightCurve(frames=sorted(glob("/data/V1234/*.fits")))
curve.set_stars(target=(210.51, 33.02),
                comparisons=[(210.48, 33.05, 11.42), (210.55, 32.99, 12.08)],
                check=(210.60, 33.11))
curve.output_aavso = "/data/V1234/aavso.txt"
app.run(curve)
```

## Parameters

- **`frames`** — *pathlist*. The series, in any order (points are sorted by date).
- **`target`**, **`comparisons`**, **`check`** — *str*. See above. The check star is measured
  exactly like the target but never used to correct it: **its flatness is the proof the run
  is sound**.
- **`mode`** — *enum*, default `ensemble`.
- **`aperture_radius`**, **`annulus_inner`**, **`annulus_outer`** — *real*, pixels.
- **`channel`** — *int*, default `-1` (luminance).
- **`matching`** — *enum*, default `auto` (WCS then star matching); `wcs` refuses a frame
  without a solution rather than falling back silently.
- **`recenter`** — *bool*, default true.
- **`use_cache`** — *bool*, default true.
- **`obscode`**, **`filter`**, **`chart`**, **`notes`** — *str*, AAVSO header fields.
  `notes` doubles as the star name in the export.
- **`output_csv`**, **`output_aavso`** — *path*. Written from the domain, so from a script
  too — the interface button will only ever fill these in.

## Tips & pitfalls

> **Warning** — always declare a **check star**. Without it, nothing distinguishes a real
> variation from a drifting aperture, a passing cloud, or a comparison star that is itself
> variable. A flat check curve is what makes the target curve believable.

> **Note** — dates are **JD**, not BJD. The barycentric correction needs the observer's
> position and the target's, and the AAVSO format accepts JD (`#DATE=JD`). Siril stops at
> the same place.

- The aperture should be roughly 2 to 3 times the FWHM: too small loses a seeing-dependent
  fraction of the flux, too large collects background noise and neighbours.
- Frames with no `DATE-OBS` are measured and kept in `.result`, but **omitted** from the
  AAVSO export: an observation without an instant is not an observation.
- Comparison stars should bracket the target in brightness and colour, and sit in the same
  part of the field.

## See also

- [AperturePhotometry](retina-doc://AperturePhotometry) — the same measurement on a single
  image, with automatic source detection.
- [ConeSearch](retina-doc://ConeSearch) — identify what is in the field, including the
  variable you are after.
- [SubframeSelector](retina-doc://SubframeSelector) — the same measure-then-judge design, on
  frame quality.
- [PlateSolve](retina-doc://PlateSolve) — obtain the WCS that makes celestial designation
  possible.

## References

- AAVSO — *Extended File Format* specification.
- Howell, S. B. — *Handbook of CCD Astronomy*, ch. 5.
