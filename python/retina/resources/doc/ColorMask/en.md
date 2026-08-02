---
id: ColorMask
category: MaskGeneration
title: Colour Mask
brief: Builds a mask selecting a range of hues, with saturation and lightness thresholds.
keywords: [mask, hue, colour, HSV, saturation, Ha, chromatic selection]
related: [RangeSelection, StarMask, ColorSaturation, SCNR]
icon: color-swatch
references:
  - "PixInsight — ColorMask script."
---

## Summary

`ColorMask` is the chromatic counterpart of [RangeSelection](retina-doc://RangeSelection), which
only knows how to select *intensities*. It produces a mask (1 channel, new window) keeping the
pixels whose **hue** falls in a range.

What it is for: strengthening the Hα regions of a nebula without touching the rest, correcting
the green cast of stars, desaturating a blue halo. These are gestures a luminance mask cannot
make — hue has nothing to do with lightness.

![Source image — ColorMask](figures/source.webp)
![Generated mask — ColorMask](figures/mask.webp)

*The source image, and the mask of the selected hue range.*

## Three traps, and how they are handled

**Hue is circular.** Red sits at both 0° and 360°. A range "from 340 to 20" must therefore cross
zero, and a naive `h ≥ min and h ≤ max` would select nothing — precisely for the most requested
colour. The process works on the **circular distance** to `hue_center`, which closes the circle
by construction.

**A hue without saturation does not exist.** On a grey pixel, hue is a rounding artefact: it can
be anything. Hence `min_saturation`.

**And on a dark background, `min_saturation` protects nothing.** HSV saturation is a *ratio*,
$(\max - \min)/\max$: a sky background at 0.06 with 0.01 of noise shows a saturation of 0.4, as
"colourful" as a solid patch. It is `min_lightness` that excludes the background. The two guards
do not do the same job, and you often need both.

## Parameters

- **`hue_center`** — *real*, default `0.0`, range `0`–`360`. Target hue, in degrees. Landmarks:
  red 0, yellow 60, green 120, cyan 180, blue 240, magenta 300.
- **`hue_width`** — *real*, default `30.0`. **Half**-width of the sharp range, in degrees.
- **`fuzziness`** — *real*, default `15.0`. Width of the ramp beyond the sharp range. At zero
  the mask is binary — and looks it on the processed image.
- **`min_saturation`** — *real*, default `0.1`. Below it, a pixel is deemed hueless.
- **`min_lightness`** / **`max_lightness`** — *real*, defaults `0.0` / `1.0`. Lightness bounds.
- **`smoothness`** — *real*, default `0.0`. Gaussian smoothing of the mask, in pixels.
- **`invert`** — *bool*, default `False`.

Produces a **new window** with one channel, like `StarMask` and `RangeSelection`.

## Tips & pitfalls

> **Always soften a little.** A binary mask leaves stair-stepped edges that show on the
> processed image. `fuzziness` softens in hue space, `smoothness` in image space; both are
> useful, and not in the same place.

- On **linear** data almost everything is dark: set `min_lightness` low and rely on saturation
  instead. On stretched data, the opposite.
- To isolate Hα in an RGB image, target red (0°) with a narrow width; most red stars will come
  along too — combine with an inverted `StarMask`.

## See also

- [RangeSelection](retina-doc://RangeSelection) — the same gesture, on intensity.
- [StarMask](retina-doc://StarMask) — star mask, to combine with.
- [ColorSaturation](retina-doc://ColorSaturation) — act on saturation per hue, without a mask.
- [SCNR](retina-doc://SCNR) — the special case of green, handled directly.

## References

- PixInsight — *ColorMask* script.
