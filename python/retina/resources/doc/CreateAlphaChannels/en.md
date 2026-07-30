---
id: CreateAlphaChannels
category: ColorSpaces
title: CreateAlphaChannels
brief: Adds (or replaces) the alpha channel from a constant, the luminance, or another view.
keywords: [alpha, transparency, channel, RGBA, PNG]
related: [ExtractAlphaChannels, ChannelCombination, ChannelExtraction]
icon: stack-2
---

## Summary

`CreateAlphaChannels` appends an **alpha channel** to the image — grayscale images become
gray+alpha (2 channels), color images become RGBA (4 channels), the PixInsight convention
carried by the `(H, W, C)` model. The alpha can be a constant, the image's own luminance,
or the first channel of another open view.

## Use cases

- **Export a PNG with transparency** (`app.save`) — the natural outlet of this process.
- **Carry a mask with the image**: store a star mask as alpha before export.
- Prepare compositions for external editors that honor RGBA.

## How it works

The alpha is clipped to $[0,1]$ and stacked after the nominal channels. `constant` fills
with **Constant value**; `luminance` uses the Rec. 709 weights on color images (or the
single channel in grayscale); `view` samples the first channel of **Source view**, which
must have the same geometry.

## Parameters

- **Alpha source** — `constant`, `luminance`, or `view`.
- **Constant value** — the uniform alpha, default `1.0` (opaque).
- **Source view** — view identifier when the source is `view`.

## Tips

- The web viewport does not composite alpha yet: the setting `app.set_transparency_mode`
  exists domain-side, the shader still shows nominal channels only.
- JPEG has no alpha: exporting flattens to the nominal channels.

## See also

ExtractAlphaChannels, ChannelCombination
