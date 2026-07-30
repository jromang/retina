---
id: MergeCFA
category: Calibration
title: CFA Merge
brief: "Recomposes a full-resolution CFA mosaic from 4 planes (inverse of SplitCFA)."
keywords: [CFA, Bayer, mosaic, debayering, pixel shuffle, per-site calibration]
related: [SplitCFA, Debayer, CosmeticCorrection, DefectMap]
icon: grid-dots
references:
  - "Peris, V. — PixInsight SplitCFA / MergeCFA scripts (per-CFA-site processing before debayering)."
  - "Shi, W. et al. (2016) — Real-Time Single Image and Video Super-Resolution Using an Efficient Sub-Pixel Convolutional Neural Network (pixel shuffle)."
---

## Summary

`MergeCFA` recomposes a full-resolution CFA (Bayer) mosaic from **4 half-resolution planes**,
one per site of the pattern (00, 01, 10, 11). It is the exact inverse of `SplitCFA`: where
`SplitCFA` decimates a Bayer mosaic into 4 separate channels, `MergeCFA` re-interleaves those 4
channels to reform the raw CFA image at its original geometry, ready for `Debayer`.

## Use cases

- **Close a `SplitCFA` → per-site processing → `MergeCFA` round trip**: calibrate (bias/dark),
  correct hot/cold pixels, or denoise each site of the Bayer pattern **separately**, so color
  interpolation cannot spread artifacts between channels, then recompose the mosaic before
  demosaicing.
- **Isolate per-site cosmetic correction**: a defective pixel caught by `CosmeticCorrection` or a
  `DefectMap` on an individual CFA plane is fixed without contaminating neighboring sites of a
  different color, unlike correction after debayering.
- **Advanced calibration pipeline for color sensors** (OSC/DSLR): apply bias/dark per CFA channel
  to respect the gain and noise characteristics specific to each Bayer filter site.

## How it works

`MergeCFA` expects a **4-channel** image — typically the output of `SplitCFA`, possibly
reprocessed in between (calibration, cosmetic correction, denoising). Each channel $i$ holds the
subsampled data of site $i$ of the CFA's $2\times2$ pattern, at resolution $H \times W$ (half the
original mosaic in each dimension).

The operator simply re-indexes the 4 planes into a single-channel $2H \times 2W$ grid, placing
each plane back at its original site position (even/odd rows and columns) — a purely geometric
operation, with no interpolation or value computation. If the supplied image has fewer than 4
channels, `MergeCFA` returns it unchanged (a copy), a defensive fallback so a pipeline mistakenly
applied to an already mono/RGB image does not error out.

## Mathematics

Let $P_0, P_1, P_2, P_3$ be the four input planes, each of size $H \times W$. The reconstructed
mosaic $M$, of size $2H \times 2W$, is defined pixel by pixel by:

$$
M(2i,\,2j) = P_0(i,j), \qquad M(2i,\,2j{+}1) = P_1(i,j),
$$
$$
M(2i{+}1,\,2j) = P_2(i,j), \qquad M(2i{+}1,\,2j{+}1) = P_3(i,j),
$$

for $0 \le i < H$ and $0 \le j < W$. This is exactly the inverse of `SplitCFA`'s decimation:

$$ \texttt{MergeCFA}\big(\texttt{SplitCFA}(M)\big) = M $$

for any mosaic $M$ with even dimensions. This operation is a **pixel shuffle** (also called
*depth-to-space*, scale factor 2): it rearranges information carried on the channel axis onto the
spatial axis, with no interpolation involved — the same principle as the sub-pixel upsampling
layer used in super-resolution (Shi et al., 2016), applied here to CFA packing instead of feature
channels.

## Parameters

This process has no parameter: it is a purely geometric, deterministic operation with no user
setting.

## Tips & pitfalls

> **Warning** — `MergeCFA` does not know the actual CFA pattern (RGGB, GRBG, BGGR, GBRG): it
> places each channel $i$ back at a **fixed** site position. The channel order produced by
> `SplitCFA` must be preserved exactly (no reordering, selection, or dropping of channels) between
> the two calls, otherwise the reconstructed mosaic is inconsistent and `Debayer` will produce
> false colors.

> **Note** — applied to an image with fewer than 4 channels, `MergeCFA` returns an unchanged copy
> without error. This is a safety net, not an implicit debayering step: check the channel count if
> the result seems to have done nothing.

- If the original mosaic had an odd dimension, `SplitCFA` will have truncated it to an even size
  before splitting the planes: the `SplitCFA` → `MergeCFA` round trip then loses the trailing row
  and/or column.
- The output is always a **single-channel** image (raw CFA mosaic, not yet color): chain it with
  `Debayer` to obtain an RGB image.

## See also

- [SplitCFA](retina-doc://SplitCFA) — inverse operation: decomposes the mosaic into 4 planes.
- [Debayer](retina-doc://Debayer) — demosaics the reconstructed CFA mosaic into a color image.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — hot/cold pixel correction, applicable
  per site between `SplitCFA` and `MergeCFA`.
- [DefectMap](retina-doc://DefectMap) — static defect map, also applicable per CFA site.

## References

- Peris, V. — PixInsight *SplitCFA* / *MergeCFA* scripts (per-CFA-site processing before
  debayering).
- Shi, W. et al. (2016) — *Real-Time Single Image and Video Super-Resolution Using an Efficient
  Sub-Pixel Convolutional Neural Network* (pixel shuffle).
