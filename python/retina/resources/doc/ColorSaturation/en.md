---
id: ColorSaturation
category: IntensityTransformations
title: Color Saturation
brief: Adjusts the overall color saturation of the image through a multiplicative factor in HSV space.
keywords: [saturation, HSV, color, chrominance, intensity, SCNR]
related: [SCNR, CurvesTransformation, ColorCalibration, RGBWorkingSpace]
icon: color-swatch
references:
  - "scikit-image — skimage.color.rgb2hsv / hsv2rgb."
  - "Foley, van Dam et al. — Computer Graphics: Principles and Practice (HSV model)."
---

## Summary

`ColorSaturation` boosts or reduces the intensity of the image's colors by acting on the **S**
(saturation) component of **HSV** (Hue/Saturation/Value) space. It is a simple, single-slider
global adjustment: a multiplicative factor applied to the saturation channel, applied identically
across the whole image. Unlike `SCNR` (which specifically targets green) or `ColorCalibration`
(which rebalances per-channel gains), `ColorSaturation` changes neither hue nor perceived
brightness: it pushes or pulls "colorfulness" without touching the image's tonal structure.

![Before — ColorSaturation](figures/before.webp)
![After — ColorSaturation](figures/after.webp)

*Before, and after doubling saturation — hue and luminance unchanged.*

## Use cases

- **Bring out color** in nebulae or galaxies whose chromatic signal is faint after stretching
  (non-linear stretches tend to desaturate the image).
- **Add punch to colors** in a planetary image or a star field rich in colored stars, at the end
  of processing.
- **Reduce excessive saturation** (amplified chroma noise, debayering artifacts) using a factor
  below 1.
- **Fully desaturate** (factor 0) to produce a grayscale-looking result while keeping the RGB
  color space (compare with `ConvertToGrayscale`).

## How it works

The process converts the image's first three channels (RGB) from RGB space to HSV space via
`skimage.color.rgb2hsv`, after clipping values to `[0, 1]` (rgb2hsv requires non-negative,
normalized input). It then multiplies the **S** channel by the `saturation` parameter, re-clipping
the result to `[0, 1]`, and converts back to RGB via `hsv2rgb`. The **H** (hue) and **V**
(value/brightness) channels are never modified: the perceived luminance of each pixel stays
globally stable — only the "purity" of the color changes.

If the image has fewer than 3 channels (monochrome), the process is a no-op and returns an
unchanged copy of the data. If the image has additional channels beyond RGB (alpha, etc.), only
the first three are processed; the rest are preserved as-is.

## Mathematics

For each RGB pixel $(r, g, b) \in [0,1]^3$, the conversion to HSV gives a hue $h$, saturation $s$
and value $v$ such that:

$$ v = \max(r, g, b), \qquad
   s = \begin{cases} 0 & \text{if } v = 0 \\ \dfrac{v - \min(r,g,b)}{v} & \text{otherwise} \end{cases} $$

Let $k$ = `saturation` be the user-set factor. The process applies:

$$ s' = \operatorname{clip}(k \cdot s,\; 0,\; 1) $$

and leaves $h$ and $v$ unchanged, before converting $(h, s', v)$ back to $(r', g', b')$ through
the inverse HSV → RGB transform. With $k = 1$ the image is unchanged (identity). With $k = 0$,
$s' = 0$ for every pixel: the image becomes a pure gray level (in terms of $v$), still encoded as
3 equal RGB channels. With $k > 1$, saturation grows proportionally until it clips at $s' = 1$
(fully saturated color), beyond which the effect visually plateaus.

## Parameters

- **`saturation`** — *real*, default `1.5`, range `0.0`–`5.0`. Multiplicative factor applied to
  the HSV saturation channel. `1.0` = no change; `< 1` desaturates (down to `0` = grayscale);
  `> 1` oversaturates.

## Tips & pitfalls

> **Warning** — a high factor (`> 2`) strongly amplifies chroma noise in weakly saturated areas
> (sky background, star halos), which can show up as blotchy color speckles. Denoise chrominance
> (`NoiseReduction` on the color channels, or `ComponentSeparation` plus separate luminance
> processing) before pushing saturation up.

- Saturation is expressed in HSV, a perceptually coarse non-linear space: the same `saturation`
  factor can give very different results depending on the image's dominant hue (green and magenta
  do not "respond" the same way).
- For finer, hue-targeted control, prefer `CurvesTransformation` on the saturation curve, which
  lets you target specific hue ranges.
- This process always operates on the first 3 channels: apply it **after** any `Debayer` or
  `ConvertToRGBColor` step, never on raw monochrome data.

## See also

- [SCNR](retina-doc://SCNR) — targeted removal of a color cast (typically green).
- [CurvesTransformation](retina-doc://CurvesTransformation) — free-curve tonal and chromatic
  control, including saturation.
- [ColorCalibration](retina-doc://ColorCalibration) — color balancing through per-channel gains.
- [RGBWorkingSpace](retina-doc://RGBWorkingSpace) — channel weighting used to compute luminance.

## References

- scikit-image — *skimage.color.rgb2hsv* / *hsv2rgb*.
- Foley, van Dam et al. — *Computer Graphics: Principles and Practice* (HSV model).
