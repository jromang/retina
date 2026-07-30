---
id: LRGBCombination
category: ColorSpaces
title: LRGB Combination
brief: Injects a luminance view into the current RGB chrominance through the L*a*b* space.
keywords: [LRGB, luminance, chrominance, Lab, combination, color]
related: [ChannelCombination, ChannelExtraction, ColorSaturation, ComponentSeparation]
icon: layers-linked
references:
  - "PixInsight — LRGBCombination tool reference."
  - "CIE — L*a*b* color space (CIE 1976)."
  - "scikit-image — skimage.color.rgb2lab / lab2rgb."
---

## Summary

`LRGBCombination` performs the classic **LRGB** combination used in planetary and deep-sky
imaging: a **luminance** image (typically finer, deeper, often shot unfiltered or in
Ha/OIII for sharpness) is injected into the **lightness** channel of a color RGB image,
while the RGB's **chrominance** (hue and saturation) is preserved. The operation works in
the perceptual **L\*a\*b\*** space: the `L*` channel carries lightness, the `a*`/`b*` channels
carry color, which lets one be substituted without disturbing the other.

## Use cases

- **Combine a dedicated luminance** (long exposure, clear filter, or synthetic luminance)
  with a noisier or lower-resolution RGB image, gaining sharpness and depth without
  sacrificing color.
- **Re-inject a reworked luminance** (denoised, deconvolved, separately stretched) into a
  color composition whose hue is already satisfactory.
- **Blend two detail sources progressively** via `weight`, e.g. dosing between the RGB's
  native luminance and a deeper external luminance.
- Final step of an **L + RGB** workflow before export, after each channel has been
  independently aligned and stretched.

## How it works

1. The current view (RGB, values assumed in `[0, 1]`) is clipped and converted to
   `L*a*b*` (`skimage.color.rgb2lab`), separating lightness (`L*`) from color (`a*`, `b*`).
2. The view named by `luminance` is resolved by its identifier through the application's
   view registry (`process.context.resolve_image_full`); its first channel is extracted and
   treated as the new luminance, assumed normalized to `[0, 1]`.
3. That luminance is scaled to the `L*` range (`[0, 100]`) and **linearly blended** with the
   existing lightness according to `weight`: at `weight = 1`, `L*` is fully replaced; at
   `weight = 0`, the original image comes out unchanged (up to Lab round-trip rounding).
4. The recombined `L*a*b*` triplet is converted back to RGB (`lab2rgb`) and re-clipped to
   `[0, 1]`. Any alpha channel (4th channel) is passed through unchanged.
5. If `luminance` is empty, the view cannot be found, or the image has fewer than 3
   channels, the process is a **no-op** (unchanged copy).

## Mathematics

Let $I_{rgb}$ be the current RGB image clipped to $[0,1]$, and
$(L, a, b) = \operatorname{RGB2Lab}(I_{rgb})$ its representation in the CIE L\*a\*b\* space
(scikit-image's default D65 illuminant), where $L \in [0,100]$ is perceptual lightness and
$(a, b)$ carry chrominance, independent of brightness.

Let $\ell(x,y)$ be the first channel of the external luminance view, rescaled to the `L*`
range:

$$ L_{\text{new}}(x,y) = 100 \cdot \ell(x,y). $$

The blend, controlled by the weight $w$ = `weight` $\in [0,1]$, is a **linear interpolation**
on the `L*` channel only:

$$ L'(x,y) = (1 - w)\, L(x,y) \;+\; w \, L_{\text{new}}(x,y), $$

with chrominance channels left unchanged: $a' = a$, $b' = b$. The final image is:

$$ I'_{rgb} = \operatorname{clip}\!\big(\operatorname{Lab2RGB}(L', a', b'),\; 0,\; 1\big). $$

Since $a$ and $b$ are never modified, the original image's **perceptual hue and saturation**
are preserved exactly; only lightness changes — precisely the property an LRGB combination
is meant to provide.

## Parameters

- **`luminance`** — *str*, default `""`. Identifier of the view to use as the luminance
  source. Must name an existing view with at least one channel; its first channel is used.
  If empty or not found, the process does nothing.
- **`weight`** — *real*, default `1.0`, range `0`–`1`. Weight of the new luminance in the
  blend with the existing `L*`. `1.0` = full replacement, `0.0` = unchanged RGB image,
  intermediate values = a progressive fade.

## Tips & pitfalls

> **Warning** — the luminance view must have **exactly the same geometry** (width, height)
> as the target RGB view and must be **already aligned** with it: the process does not
> resize or register the images. Run `StarAlignment` or `FeatureAlignment` beforehand if the
> L and RGB exposures come from separate acquisitions.

> **Note** — the external luminance must be supplied **normalized to `[0, 1]`** (a linear
> image, or one already stretched consistently with the RGB). An unnormalized luminance will
> produce an out-of-range `L*`, silently clipped by `lab2rgb`.

- Stretch and denoise the luminance **separately** before combining: it is the carrier of
  fine detail, and LRGB combination exists precisely so it can be processed independently
  of the RGB's chromatic noise.
- To build the luminance itself from several channels (Ha, OIII, or a master L), use
  `PixelMath` or `ChannelCombination` upstream, then pass the result as `luminance`.
- A `weight` near `0.5` gives a soft compromise between the native RGB's sharpness and that
  of a deeper luminance, useful when the latter is slightly noisy.

## See also

- [ChannelCombination](retina-doc://ChannelCombination) — assemble separate channels into a color image.
- [ChannelExtraction](retina-doc://ChannelExtraction) — extract a channel or luminance from a color image.
- [ColorSaturation](retina-doc://ColorSaturation) — adjust saturation after combination.
- [ComponentSeparation](retina-doc://ComponentSeparation) — separate luminance and chrominance (PCA/ICA).

## References

- PixInsight — *LRGBCombination* tool reference.
- CIE — *L\*a\*b\** color space (CIE 1976).
- scikit-image — `skimage.color.rgb2lab` / `lab2rgb`.
