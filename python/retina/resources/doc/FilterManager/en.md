---
id: FilterManager
category: ColorCalibration
title: Spectral Curve Manager
brief: Lists, adds and removes filter transmission, sensor QE and white reference curves.
keywords: [filter, sensor, quantum efficiency, spectrum, SPCC, colour calibration, transmission]
related: [SpectrophotometricColorCalibration, PhotometricColorCalibration, ColorCalibration]
icon: adjustments-horizontal
references:
  - "siril-spcc-database — community database of filter and sensor curves (GPL-3)."
---

## Summary

`FilterManager` is the scriptable counterpart of the spectral curve database used by
[SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration). It
answers three questions: **what do I have**, **what does this curve look like**, and **how do
I add my own**.

Three families of curves:

| `kind` | What it is |
|---|---|
| `filter` | Filter transmission, as a fraction from 0 to 1. |
| `sensor` | Sensor quantum efficiency, same scale. |
| `white_reference` | A spectrum declared neutral — average spiral galaxy, solar-type star… |

## Where the bundled curves come from

From the [siril-spcc-database](https://gitlab.com/free-astro/siril-spcc-database), under
**GPL-3** and therefore compatible with Retina's licence, digitized and verified by the Siril
community from manufacturer documents. Every file cites its source and licence in its header;
`action = show` returns them to you.

Retina bundles a **subset** — common CMOS sensors, the RGB sets of the main manufacturers, a
few white references. The rest is added through `action = add`.

**Narrowband** filters are deliberately absent from the database: a 3 or 7 nm band is better
described by its central wavelength and width (the SPCC's `narrowband` mode) than by a curve
traced off a scanned chart.

## Your curves come first

A curve you add under an **already bundled** identifier shadows it: that is how you fix a
curve you believe wrong without touching the installation. Removing it (`action = remove`)
brings the bundled one back. A bundled curve itself cannot be deleted — the request raises,
rather than silently doing nothing.

Your files live under `<config>/spectra/{filters,sensors,whiteref}/`, as two-column CSV.
Nothing stops you editing them by hand: that is the point of the format.

## Parameters

- **`action`** — *enum* `list` | `show` | `add` | `remove`, default `list`.
- **`kind`** — *enum* `filter` | `sensor` | `white_reference`, default `filter`.
- **`name`** — *str*. The curve identifier (the filename without extension).
- **`label`** — *str*. Readable name, for `add`.
- **`channel`** — *str*. Associated channel (`red`, `green`, `blue`, `lum`…), for `add`.
- **`points`** — *floatlist*. The curve, flattened: `[λ₁, v₁, λ₂, v₂, …]`, wavelengths in
  nanometres and values as fractions.

The result is in `.result` — this is a measurement process; it transforms no image.

## Examples

```python
# What is available
fm = FilterManager(action='list', kind='sensor')
fm.execute_global(app)
print([c['id'] for c in fm.result['curves']])

# Add your own filter curve
FilterManager(action='add', kind='filter', name='my_red', label='My R',
              channel='red',
              points=[580.0, 0.02, 600.0, 0.9, 680.0, 0.92, 700.0, 0.05]
              ).execute_global(app)
```

## Tips & pitfalls

> **Value scale**: manufacturer documents give sometimes percentages, sometimes fractions.
> Retina normalizes everything to fractions at load — a curve whose maximum exceeds 1.5 is
> taken to be in percent. So there is no need to convert yourself, but do not mix the two in
> one file.

- A curve needs at least **two points**. Outside its support transmission is zero, not
  extended: cover the whole useful band, or you truncate the channel response.
- The filename is the identifier: no spaces, lowercase, it is simply more convenient.

## See also

- [SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration) — the
  consumer of these curves.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — the version
  without curves, on Gaia magnitudes alone.

## References

- siril-spcc-database — community database of filter and sensor curves (GPL-3).
