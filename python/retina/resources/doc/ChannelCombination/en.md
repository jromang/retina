---
id: ChannelCombination
category: ColorSpaces
title: Channel Combination
brief: Assembles three separate views (by identifier) into an RGB image, channel by channel.
keywords: [channels, RGB, combination, color, narrowband, monochrome, SHO]
related: [ChannelExtraction, LRGBCombination, ConvertToRGBColor, ComponentSeparation]
icon: layers-linked
references:
  - "PixInsight — ChannelCombination tool reference."
  - "numpy.dstack — stacking arrays along the third axis."
---

## Summary

`ChannelCombination` rebuilds a color image by assembling three existing views — referenced
by their **identifier** — into the **R**, **G** and **B** channels of the resulting view
respectively. It is the inverse operation of `ChannelExtraction`: where that process splits
an RGB image into isolated components, `ChannelCombination` glues them back together. It is
used both to reassemble a classic RGB after per-channel processing and to build a
**narrowband false-color** composite (SHO/HOO palette) from three monochrome captures.

## Use cases

- **Rebuild an RGB** after processing `ChannelExtraction`(R), (G) and (B) independently
  (different stretch, denoise or deconvolution per channel).
- **Compose a narrowband palette**: assign Ha → R, OIII → G, SII → B (SHO/Hubble palette),
  or Ha → R, OIII → G, OIII → B (bicolor HOO), from calibrated monochrome views.
- **Build a manual LRGB composite** channel by channel before refining luminance with
  `LRGBCombination`.
- **Try out channel assignments** quickly by simply changing the view identifiers, without
  duplicating or re-stacking the data.

## How it works

The process takes three string parameters — `r`, `g`, `b` — each holding the **identifier**
of an already-open view. For each channel:

1. If the identifier is empty, the channel falls back to the **first channel of the current
   image** (the one the process runs on) — useful when only one or two channels need to be
   replaced while the others stay unchanged.
2. Otherwise, the corresponding view is resolved through the internal open-image registry
   (`retina.process.context.resolve_image_full`) and its **first channel** (index 0) is
   extracted — if the referenced view is already RGB, only its red channel is used.
3. If the identifier does not match any open view, the process silently falls back to the
   current image's channel (same behavior as an empty identifier).

The three resulting channels (which must share the same `H×W` geometry) are stacked along
the third axis to form an `(H, W, 3)` float32 image.

## Mathematics

There is no photometric transformation: the operation is a **pure rearrangement** of samples,
with no interpolation or weighting. Denoting $S_R$, $S_G$, $S_B$ the 2D source arrays (first
channel of views `r`, `g`, `b`, or of the current image by default), the result $I$ is the
stack:

$$ I(x, y) = \big(S_R(x,y),\; S_G(x,y),\; S_B(x,y)\big) $$

i.e., in array notation, $I = \operatorname{dstack}(S_R, S_G, S_B)$. No clipping is applied:
output values directly inherit the source range (typically $[0,1]$ for already-normalized
images).

## Parameters

- **`r`** — *str*, default `""`. Identifier of the view to place in the red channel. Empty →
  falls back to the current image's channel.
- **`g`** — *str*, default `""`. Identifier of the view to place in the green channel. Empty →
  falls back to the current image's channel.
- **`b`** — *str*, default `""`. Identifier of the view to place in the blue channel. Empty →
  falls back to the current image's channel.

## Tips & pitfalls

> **Warning** — if a referenced view is already color, only its **channel 0 (red)** is used;
> that view's green and blue are silently ignored. Use `ChannelExtraction` beforehand to
> cleanly isolate a monochrome channel before combining.

> **Note** — an identifier that resolves to nothing (closed view, typo) raises **no error**:
> the corresponding channel quietly falls back to the current image. Check view identifiers
> (`app.windows`) if the result looks unexpected.

- The three source views must share the **same geometry** (width/height); otherwise
  `numpy.dstack` fails with a shape error.
- For a classic narrowband palette, align and stretch each monochrome channel *before*
  combination — `ChannelCombination` performs no stretching or balancing of its own.
- A light `ColorCalibration` or `SCNR` pass after combination often corrects a green cast
  or a color-balance mismatch introduced by processing channels separately.

## See also

- [ChannelExtraction](retina-doc://ChannelExtraction) — the inverse operation: isolating a channel.
- [LRGBCombination](retina-doc://LRGBCombination) — inject a luminance into an existing RGB.
- [ConvertToRGBColor](retina-doc://ConvertToRGBColor) — convert a mono image to RGB color space.
- [ComponentSeparation](retina-doc://ComponentSeparation) — decomposition into independent components.

## References

- PixInsight — *ChannelCombination* tool reference.
- numpy — *dstack*, stacking arrays along the third axis.
