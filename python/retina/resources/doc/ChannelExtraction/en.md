---
id: ChannelExtraction
category: ColorSpaces
title: Channel Extraction
brief: Extracts an R, G, B channel or a weighted luminance from a color image into a single-channel image.
keywords: [channel, RGB, luminance, extraction, grayscale, color separation]
related: [ChannelCombination, ConvertToGrayscale, ComponentSeparation, SCNR]
icon: layers-linked
references:
  - "PixInsight — ChannelExtraction tool reference (RGB/CIE color spaces)."
  - "ITU-R BT.709 — relative luminance coefficients."
---

## Summary

`ChannelExtraction` isolates one channel of an RGB color image and produces a new
single-channel image. It can extract the **R**, **G**, or **B** channel directly, or
compute a Rec. 709-weighted **luminance** `L`. On an image that is already grayscale
(a single channel), the process is a plain pass-through that copies the data.

## Use cases

- **Isolate a channel** to analyze or process it independently (selective denoising,
  inspecting the noise specific to one filter, diagnosing a saturated channel).
- **Extract a luminance** ahead of an LRGB-style workflow (stretch luminance separately
  from chrominance, then recombine via `LRGBCombination`).
- **Prepare masks** from a specific channel (e.g. a sharper star mask on the green
  channel, often the least noisy on a Bayer sensor).
- **Diagnose a color imbalance** by visually comparing separately extracted R, G, and B.

## How it works

The process reads the active view's `(H, W, C)` pixel array:

- If the image has only **one channel** (already mono), the data is copied as-is — the
  extraction has no effect.
- If `channel` is `R`, `G`, or `B`, the corresponding channel (index 0, 1, or 2) is
  sliced out and copied into a `(H, W, 1)` array.
- If `channel` is `L`, a **weighted luminance** is computed as a linear combination of
  the three channels, using the **ITU-R BT.709** coefficients (the same weights used for
  standard perceptual RGB-to-grayscale conversion).

In all cases, the result is a single-channel `float32` image.

## Mathematics

Let $R(x,y)$, $G(x,y)$, $B(x,y)$ be the three planes of the input image. For extracting a
primary channel, the output is simply a projection:

$$ I'(x,y) = C(x,y), \qquad C \in \{R, G, B\} \text{ selected by the } \texttt{channel} \text{ parameter}. $$

For luminance ($\texttt{channel} = \texttt{L}$), the output is the linear combination:

$$ L(x,y) = 0.2126\, R(x,y) + 0.7152\, G(x,y) + 0.0722\, B(x,y). $$

These coefficients (Rec. 709) reflect the relative sensitivity of the human eye: green
dominates perceived brightness, blue contributes the least. They differ from the Rec. 601
weights (0.299 / 0.587 / 0.114) sometimes used elsewhere — `ChannelExtraction` always
uses Rec. 709.

## Parameters

- **`channel`** — *enum*, default `L`, choices: `R`, `G`, `B`, `L`. Channel to extract:
  one of the three primary channels, or `L` for the Rec. 709-weighted luminance computed
  from all three channels.

## Tips & pitfalls

> **Note** — on an already single-channel image, the process just copies the data:
> there is nothing left to "extract".

> **Warning** — luminance `L` is **not** a plain average of the channels: the Rec. 709
> weights strongly favor green. On images with a strong red or blue bias (Hα nebulae, for
> instance), the extracted luminance can under-represent the real signal in those channels.

- To rebuild a color image from extracted channels (possibly processed separately), use
  `ChannelCombination`.
- For an RGB-to-grayscale conversion that replaces the image directly (rather than
  extracting a mono-channel copy), see `ConvertToGrayscale`.
- To separate color into statistically independent components (PCA/ICA) instead of raw
  RGB channels, see `ComponentSeparation`.

## See also

- [ChannelCombination](retina-doc://ChannelCombination) — recomposes an RGB image from three views/channels.
- [ConvertToGrayscale](retina-doc://ConvertToGrayscale) — RGB-to-grayscale conversion of the whole image.
- [ComponentSeparation](retina-doc://ComponentSeparation) — separation into independent components (PCA/ICA).
- [SCNR](retina-doc://SCNR) — targeted treatment of one channel (typically green) without extracting it.

## References

- PixInsight — *ChannelExtraction* tool reference (RGB/CIE color spaces).
- ITU-R BT.709 — relative luminance coefficients.
