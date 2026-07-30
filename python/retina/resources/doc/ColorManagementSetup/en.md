---
id: ColorManagementSetup
category: ColorManagement
title: Color Management Setup
brief: Sets the global color-management defaults (working profile, rendering intent) used by the other ICC processes.
keywords: [ICC, color, color profile, color management, rendering intent, sRGB, littlecms]
related: [AssignICCProfile, ICCProfileTransformation, ConvertToRGBColor, RGBWorkingSpace]
icon: settings
references:
  - "PixInsight — ColorManagementSetup process reference."
  - "International Color Consortium — ICC.1:2022 specification."
  - "Pillow — PIL.ImageCms (littlecms bindings)."
---

## Summary

`ColorManagementSetup` is a **global**, **pixel-free** process: it does not touch any image, but
sets the **default color-management (ICC) settings** subsequently used by the other tools in the
`ColorManagement` category — chiefly `ICCProfileTransformation` and, indirectly, raster export
(TIFF/PNG/JPEG). It is the equivalent of PixInsight's global configuration dialog: run it once
(or whenever the working context changes), not per window.

## Use cases

- **Set the working profile once for a session** (`working_profile`), typically `sRGB` for
  web/sharing output, or a wide-gamut profile (Adobe RGB, ProPhoto RGB) for a high-gamut editing
  workflow destined for print.
- **Choose the default rendering intent** (`rendering_intent`) applied by later ICC conversions
  that do not explicitly specify one.
- **Temporarily disable color management** (`enabled = False`) for a purely scientific workflow
  where pixel values must not undergo any colorimetric reinterpretation.
- **Script a reproducible context**: call `ColorManagementSetup(...).execute_global(app)` at the
  top of a recipe to guarantee that all subsequent exports share the same setting.

## How it works

Retina works internally on **scene-linear** float32 data; ICC management only matters for
**rendering and export** at 8/16 bits, where it relies on `PIL.ImageCms` (the Python bindings for
the **littlecms** library).

`ColorManagementSetup` simply writes three values into a **module-level global configuration
dict** (`_CMS_SETTINGS`), shared across the whole running Python process: the working profile
name, the default rendering intent, and an enabled flag. It does not open, load, or modify any
image — hence `is_global = True` and no output window (`creates_window = False`). Its only side
effect is to prepare the context later read by the other ICC processes (through `_load_profile`,
which resolves `"sRGB"` into an on-the-fly littlecms profile, or any other name into a path to an
`.icc`/`.icm` file).

## Mathematics

This process defines no numerical transformation on pixels, so it has no mathematics of its own.
The relevant formulas (color-space conversion matrices, tone curves, computation of the
perceptual / relative colorimetric / saturation / absolute colorimetric rendering intents in the
ICC sense) are implemented by littlecms at the point where `ICCProfileTransformation` consumes
these settings, not here.

## Parameters

- **`working_profile`** — *str*, default `sRGB`. Name of the global working profile (`"sRGB"` for
  the standard sRGB profile generated on the fly, or a path to an `.icc`/`.icm` file for a custom
  profile, e.g. Adobe RGB or ProPhoto RGB).
- **`rendering_intent`** — *enum*, default `perceptual`, choices: `perceptual`, `relative`,
  `saturation`, `absolute`. Default ICC rendering intent applied by later profile conversions:
  `perceptual` preserves the visual relationships between hues (general photographic use),
  `relative` (relative colorimetric) preserves in-gamut colors and remaps the white point,
  `saturation` favors color vividness (graphics/charts), `absolute` (absolute colorimetric)
  preserves exact values without remapping the white point (soft-proofing use).
- **`enabled`** — *bool*, default `True`. Globally enables color management. When `False`,
  downstream ICC conversions may be bypassed for a purely numeric workflow with no colorimetric
  reinterpretation.

## Tips & pitfalls

> **Note** — this process modifies **no pixels** and creates **no window**: it is a global
> session setting, more like an application preference than an image-processing operation. Call
> it at the start of a script to fix the context before any export or any
> `ICCProfileTransformation`.

- The settings written here live in **module-level shared state** — they are not serialized into
  a view's history nor into an XISF/FITS file. For a reproducible recipe, explicitly call
  `ColorManagementSetup` at the top of the script rather than relying on state left by a previous
  session.
- To attach a profile to **one specific window** (metadata only, no pixel conversion), use
  [AssignICCProfile](retina-doc://AssignICCProfile) instead.
- To actually **convert pixels** from one color space to another, use
  [ICCProfileTransformation](retina-doc://ICCProfileTransformation), which can consume the
  settings set here as defaults.

## See also

- [AssignICCProfile](retina-doc://AssignICCProfile) — attaches an ICC profile to a window without
  touching pixels.
- [ICCProfileTransformation](retina-doc://ICCProfileTransformation) — actually converts pixels
  from a source profile to a target profile.
- [ConvertToRGBColor](retina-doc://ConvertToRGBColor) — pixel-level color-space conversion
  (grayscale to RGB).
- [RGBWorkingSpace](retina-doc://RGBWorkingSpace) — defines the RGB working space (channel
  weights) used by luminance conversions.

## References

- PixInsight — *ColorManagementSetup* process reference.
- International Color Consortium — *ICC.1:2022* specification.
- Pillow — *PIL.ImageCms* (littlecms bindings).
