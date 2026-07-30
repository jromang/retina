---
id: ExtractAlphaChannels
category: ColorSpaces
title: ExtractAlphaChannels
brief: Extracts the alpha channel into a new grayscale window, or removes it in place.
keywords: [alpha, transparency, channel, extract, remove]
related: [CreateAlphaChannels, ChannelExtraction]
icon: layers-subtract
---

## Summary

`ExtractAlphaChannels` is the reverse of `CreateAlphaChannels`, with the PixInsight split:
**extract** produces a new grayscale window holding the alpha (the source is untouched),
**remove** strips the alpha from the view in place — ordinary history, ordinary undo.

## Use cases

- **Recover a mask** stored as alpha (extract, then `app.set_mask`).
- **Flatten** an RGBA image back to RGB before a process that expects 3 channels.

## How it works

The alpha is the channel beyond the nominal ones (2nd in grayscale, 4th in color).
`extract` copies it into a `(H, W, 1)` image opened as a new window; `remove` keeps only
the nominal channels. An image without alpha raises a clear error.

## Parameters

- **Mode** — `extract` (new window) or `remove` (transform the view).

## See also

CreateAlphaChannels, ChannelExtraction
