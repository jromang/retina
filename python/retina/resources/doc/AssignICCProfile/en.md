---
id: AssignICCProfile
category: ColorManagement
title: Assign ICC Profile
brief: Attaches an ICC profile to the window as metadata, without touching the pixels.
keywords: [ICC, color profile, metadata, color management, sRGB, littlecms, export]
related: [ICCProfileTransformation, ColorManagementSetup, RGBWorkingSpace, SampleFormatConversion]
icon: certificate
references:
  - "PixInsight — ICCProfile process reference."
  - "International Color Consortium — ICC.1:2022 (Specification ICC.1)."
  - "PIL.ImageCms (littlecms) — Pillow documentation."
---

## Summary

`AssignICCProfile` **labels** a window with an ICC profile — it simply records the profile's
name or path in `view.window.icc_profile`. No color conversion is performed, no pixel is
modified: it is a **pure metadata** operation, the analogue of PixInsight's `ICCProfile` process
(not to be confused with `ICCProfileTransformation`). The attached profile will be embedded at
export time (TIFF/PNG/JPEG…) and, if needed, will guide a later explicit conversion.

## Use cases

- **Declare the color space** of an image known to have been composed in a given space (sRGB,
  Adobe RGB, a calibrated display profile…) without needing to convert pixel values.
- **Prepare an export**: embed a profile into a TIFF/PNG/JPEG so third-party software (viewers,
  social networks, print labs) interprets colors correctly.
- **Fix a wrong label**: reassign the correct profile to an image imported without one, or with
  an incorrect one, without disturbing the rendering already validated on screen.
- **Document a processing chain** before later going through a real conversion
  ([ICCProfileTransformation](retina-doc://ICCProfileTransformation)) to a target space.

## How it works

The process takes a single parameter, `profile` — a known name (`sRGB`) or a path to an
`.icc`/`.icm` file. On execution (`execute_on`), it simply writes that string to the `icc_profile`
attribute of the view's window (`view.window.icc_profile = self.profile`), provided the view has
a window. The `Image` pixel array is never touched: `execute_on_image` returns the image
**unchanged**, with no copy or recomputation — the profile lives on the window (`ImageWindow`),
not on the raw data.

Actual resolution of the profile (`ImageCms.createProfile("sRGB")` for the reserved name `sRGB`,
or `ImageCms.getOpenProfile(path)` for a file) only happens later, when another link in the chain
(export, or `ICCProfileTransformation`) actually needs to open the profile through
`PIL.ImageCms` (littlecms). `AssignICCProfile` itself therefore does not validate the file's
existence or validity at assignment time.

## Mathematics

Not applicable: this process performs no numerical transformation on the pixels and computes
nothing — it is a simple metadata write (a string) onto the window object. There is no formula,
conversion matrix, or transfer curve to document here; those belong to
[ICCProfileTransformation](retina-doc://ICCProfileTransformation), which actually converts pixel
values from a source profile to a target profile via littlecms.

## Parameters

- **`profile`** — *str*, default `sRGB`. Profile name (the reserved word `sRGB` generates a
  standard sRGB profile via littlecms) or path to a `.icc`/`.icm` profile file on disk. The
  string is stored as-is on the window; it is only resolved into a concrete ICC profile when
  another operation (export, transformation) needs it.

## Tips & pitfalls

> **Note** — this operation is **non-destructive in the strong sense**: it modifies neither the
> pixels nor even the view's history, beyond the window attribute. It therefore differs from
> most processes, which go through `begin_process()/end_process()`.

> **Warning** — assigning a profile **converts nothing**. If the pixels were actually produced
> in a color space different from the one declared, the displayed or exported colors will be
> wrong until a real conversion is applied with
> [ICCProfileTransformation](retina-doc://ICCProfileTransformation).

- An invalid file path does not fail immediately: the error only surfaces when a consumer tries
  to open the profile (export, conversion). Check the path beforehand.
- To change the global default settings (working profile, rendering intent) rather than a single
  window's profile, use [ColorManagementSetup](retina-doc://ColorManagementSetup).
- Retina's internal data is *scene-linear* float; ICC really only concerns **rendering and
  export** at 8/16 bits, not the linear processing pipeline.

## See also

- [ICCProfileTransformation](retina-doc://ICCProfileTransformation) — actually converts pixels
  from a source profile to a target profile.
- [ColorManagementSetup](retina-doc://ColorManagementSetup) — global color management settings
  (working profile, rendering intent).
- [RGBWorkingSpace](retina-doc://RGBWorkingSpace) — defines the underlying RGB working space.
- [SampleFormatConversion](retina-doc://SampleFormatConversion) — sample format conversion,
  often used downstream before export.

## References

- PixInsight — *ICCProfile* process reference.
- International Color Consortium — *ICC.1:2022 (Specification ICC.1)*.
- PIL.ImageCms (littlecms) — Pillow documentation.
