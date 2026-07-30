---
id: ICCProfileTransformation
category: ColorManagement
title: ICC Profile Transformation
brief: Converts pixels from a source ICC profile to a target profile via the ICC chain (littlecms/PIL.ImageCms).
keywords: [ICC, color management, littlecms, color profile, rendering intent, sRGB, PCS]
related: [AssignICCProfile, ColorManagementSetup, ColorCalibration, ConvertToRGBColor]
icon: transform
references:
  - "International Color Consortium — ICC.1:2022 Specification (ICC profile format)."
  - "Pillow — ImageCms module (Little CMS 2 bindings)."
  - "Little CMS project — documentation on rendering intents."
---

## Summary

`ICCProfileTransformation` actually converts pixel values from a **source** color space to a
**target** one, relying on the **littlecms** color-management engine bundled with Pillow
(`PIL.ImageCms`). Unlike `AssignICCProfile`, which merely attaches a profile as window metadata,
this process **rewrites the pixels**: it is the tool to use when you want an image's rendering to
match a specific color space (sRGB for the web, Adobe RGB/ProPhoto for printing, a custom sensor
profile…).

Our internal data is *scene-linear* float32 and normally carries no ICC profile as long as it stays
inside the processing pipeline; this transformation is meant for downstream use, at render/export
time.

## Use cases

- **Export to the web**: convert a stretched image to sRGB before a JPEG/PNG export, for consistent
  rendering across standard displays.
- **Prepare for printing**: adapt to a wider gamut (Adobe RGB, ProPhoto RGB) with a rendering intent
  suited to the output device.
- **Align an imported image** whose ICC profile differs from the working pipeline (DSLR photo, scan,
  export from another application) onto the current working profile.
- **Convert a sensor's rendering** whose custom profile was attached via `AssignICCProfile`, before
  converting back to sRGB for distribution.

## How it works

1. The image's first three channels (`RGB`) are extracted; on a monochrome image, the single channel
   is duplicated three times to form an RGB image (ICC color management operates on a color space,
   not on an isolated luminance channel).
2. Float values in `[0, 1]` are **quantized to 8 bits** (`uint8`, `0`–`255`) to build a PIL image, the
   input format expected by `ImageCms.profileToProfile`.
3. Both profiles (`from_profile`, `to_profile`) are loaded: the name `"sRGB"` instantiates littlecms's
   standard sRGB profile, any other string is treated as a path to an `.icc`/`.icm` file on disk.
4. `ImageCms.profileToProfile` performs the conversion through the profile connection space (PCS),
   using the chosen rendering intent (`intent`).
5. The resulting 8-bit image is converted back to float32 `[0, 1]` by dividing by 255. If the source
   was originally monochrome, the RGB output is collapsed to a single channel by averaging the three
   components.

## Mathematics

An ICC conversion never links two profiles directly: it goes through a **device-independent** space,
the *Profile Connection Space* (PCS, typically CIEXYZ or CIELAB). For a simple "matrix" profile (the
common case for sRGB and standard RGB spaces), the chain decomposes into a per-channel **tone
reproduction curve** (TRC) followed by a **matrix** into the PCS:

$$ C_{\text{lin}} =
\begin{cases}
C / 12.92 & C \le 0.04045 \\[4pt]
\left(\dfrac{C + 0.055}{1.055}\right)^{2.4} & C > 0.04045
\end{cases}
\qquad\qquad
\begin{pmatrix} X \\ Y \\ Z \end{pmatrix} = M_{\text{src}}
\begin{pmatrix} R_{\text{lin}} \\ G_{\text{lin}} \\ B_{\text{lin}} \end{pmatrix} $$

Converting to the target profile applies the inverse chain — matrix $M_{\text{dst}}^{-1}$ then
inverse TRC — with, in between, a **chromatic adaptation** (Bradford transform $A$) if the source and
target white points differ:

$$ \begin{pmatrix} R'_{\text{lin}} \\ G'_{\text{lin}} \\ B'_{\text{lin}} \end{pmatrix}
= M_{\text{dst}}^{-1}\, A_{W_{\text{src}} \to W_{\text{dst}}}\, M_{\text{src}}
\begin{pmatrix} R_{\text{lin}} \\ G_{\text{lin}} \\ B_{\text{lin}} \end{pmatrix} $$

The **rendering intent** (`intent`) determines how colors outside the target gamut are handled:

- **`perceptual`** — non-linearly compresses the whole gamut to preserve relative relationships
  between colors; no hard clipping, perceived as natural (recommended for general-purpose
  photo/astrophoto).
- **`relative`** (relative colorimetric) — adapts the white point then **clips** out-of-gamut colors
  to the nearest target gamut boundary; colorimetric fidelity for in-gamut tones.
- **`saturation`** — favors perceived saturation over colorimetric accuracy (business graphics,
  presentations).
- **`absolute`** — like `relative` but **without** white-point adaptation: simulates the exact
  rendering of the target device, including its own white point (used for proofing).

The intermediate 8-bit quantization introduces a discretization error of at most
$1/510 \approx 0.2\%$ in normalized value per channel — negligible for a final render, but worth
keeping in mind on very smooth gradients (see Tips).

## Parameters

- **`from_profile`** — *str*, default `sRGB`. Source color profile. `"sRGB"` loads littlecms's
  standard sRGB profile; any other string is treated as a path to an `.icc`/`.icm` file.
- **`to_profile`** — *str*, default `sRGB`. Target color profile, resolved the same way as
  `from_profile`.
- **`intent`** — *enum*, default `perceptual`, choices: `perceptual`, `relative`, `saturation`,
  `absolute`. Rendering intent applied by littlecms to handle out-of-gamut colors.

## Tips & pitfalls

> **Warning** — the current implementation quantizes the image to **8 bits** (`0`–`255`) during the
> transformation, despite what the process's internal docstring suggests. On a very smooth sky
> background gradient this can introduce slight banding; if visible, apply light dithering/noise
> after conversion, or push the ICC conversion to the very end of the export pipeline.

> **Note** — on a monochrome image, the conversion goes through a duplicated RGB image and then
> collapses back to a single channel by averaging the three outputs. Purely "Gray" ICC profiles are
> therefore not natively handled by this process.

- Use the **`perceptual`** intent for a pleasant-looking web/JPEG export, and **`relative`** when
  colorimetric fidelity matters (photometric comparison, cross-calibration).
- `ICCProfileTransformation` does not replace `ColorCalibration` / `PhotometricColorCalibration`,
  which balance color from the **astronomical signal** itself (stars, catalogs). This process acts
  downstream, on the **final presentation** of the image, once the color balance is already set.
- To attach a profile to a window without touching pixels (export metadata only), use
  `AssignICCProfile`; to set the application's global working profile, see `ColorManagementSetup`.

## See also

- [AssignICCProfile](retina-doc://AssignICCProfile) — attaches an ICC profile as metadata, without modifying pixels.
- [ColorManagementSetup](retina-doc://ColorManagementSetup) — global color management settings.
- [ColorCalibration](retina-doc://ColorCalibration) — color balancing based on the astronomical signal.
- [ConvertToRGBColor](retina-doc://ConvertToRGBColor) — internal color space conversion (mono → RGB).

## References

- International Color Consortium — *ICC.1:2022 Specification* (ICC profile format).
- Pillow — *ImageCms* module (Little CMS 2 bindings).
- Little CMS project — documentation on *rendering intents*.
