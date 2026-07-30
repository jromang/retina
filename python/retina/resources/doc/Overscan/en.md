---
id: Overscan
category: Calibration
title: Overscan correction
brief: Corrects bias drift using the sensor's unexposed overscan region, then trims it away.
keywords: [overscan, bias, drift, BIASSEC, TRIMSEC, IRAF, calibration, CCD, trim]
related: [ImageCalibration, Superbias, Crop, Integration]
icon: crop
references:
  - "IRAF — BIASSEC / TRIMSEC / DATASEC image section conventions."
  - "Howell, S. B. — Handbook of CCD Astronomy, data reduction chapter."
  - "ccdproc — subtract_overscan, trim_image."
---

## Summary

The **overscan** is a strip of pixels read out by the electronics but **never exposed to
light**. It therefore records only the sensor's electronic pedestal — the bias — but it
records it *during the exposure itself*.

That is where its value lies, and why a master bias does not replace it: the master gives
the **average bias of a series**, the overscan gives its value **at the moment of the
exposure**, thermal drift and power fluctuations included. On a real dataset (Andor Aspen
CG16M, 90 s exposures) the gap between the two reaches 20 % of the sky background: ignoring
it means being one fifth wrong about the very signal you are measuring.

## Use cases

- **Any sensor that declares a `BIASSEC`** — most scientific CCDs and some cooled CMOS. The
  automated pipeline detects it and applies it on its own.
- **Long sessions where the bias drifts**: electronics warming up through the night, an
  unstable supply, or simply no bias taken the same evening.
- **Trimming the unexposed region** first: those columns never saw the sky, and keeping them
  skews the background level, the automatic stretch and every noise measurement.

## How it works

The regions are given as **IRAF sections**, the convention most acquisition software writes
into the header: `BIASSEC` for the overscan, `TRIMSEC` for the useful area. The pipeline
reads them and fills the parameters in — where PixInsight asks you to enter them by hand,
sensor by sensor.

The level is measured with a robust estimator (median by default) **along the region**. A
strip of columns yields one level **per row**, which is the useful case: readout register
drift shows along the readout direction, not uniformly. The `auto` mode infers that
direction from the shape of the region.

Three pitfalls of the IRAF convention are handled explicitly:

1. **Order** — FITS states x first, numpy the row axis.
2. **Omission** — `[4096:4109]` gives only one dimension, and it is x. Padding it on the
   wrong side would slice rows instead of columns, silently and with a perfectly plausible
   geometry.
3. **Channels** — the section addresses geometry only; channels follow in full.

## Mathematics

Given an image $I$ of size $H \times W$, an overscan region $B$ (columns $[x_a, x_b]$) and a
useful region $T$, the level estimated at row $y$ for a per-row correction is

$$ b(y) = \operatorname{med}\big\{\, I(y, x) \;:\; x \in [x_a, x_b] \,\big\} $$

and the corrected, trimmed image is

$$ I'(y, x) = I(y, x) - b(y), \qquad (y, x) \in T $$

Median rather than mean: a few cosmic rays land in the overscan too, and a mean would let
them shift the level of a whole row.

## Parameters

- **`bias_section`** — *str*, default empty. IRAF section of the overscan (`[4096:4109]`).
  Empty: no subtraction.
- **`trim_section`** — *str*, default empty. IRAF section to keep (`[1:4096, :]`). Empty: no
  trimming.
- **`method`** — *enum*, default `median`. Level estimator (`median`, `mean`).
- **`axis`** — *enum*, default `auto`. Direction of the correction: `row` (one level per
  row), `column`, `global` (a single scalar), or `auto` from the region's shape.

## Tips & pitfalls

> **Warning** — the overscan is corrected **before** the master bias, never after: both
> measure the same thing. Applying it second would subtract the pedestal twice. The pipeline
> therefore places this step right at the front.

> **Note** — trimming must apply to **every** frame type, otherwise geometries stop
> matching: a trimmed master does not apply to an untrimmed light.

- A corrected image has a background close to zero, sometimes slightly negative: that is
  normal, and it is the job of [ImageCalibration](retina-doc://ImageCalibration)'s pedestal
  to lift it without truncating.
- If the header declares nothing, there probably is no overscan: do not invent one — a
  badly chosen region would subtract signal.

## See also

- [ImageCalibration](retina-doc://ImageCalibration) — what comes next: bias, dark, flat.
- [Superbias](retina-doc://Superbias) — multiscale model of the residual bias.
- [Crop](retina-doc://Crop) — trimming to fractional bounds.

## References

- IRAF — `BIASSEC` / `TRIMSEC` / `DATASEC` image section conventions.
- Howell, S. B. — *Handbook of CCD Astronomy*, data reduction.
- ccdproc — `subtract_overscan`, `trim_image`.
