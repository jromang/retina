---
id: NarrowbandNormalization
category: ColorCalibration
title: Narrowband Normalization
brief: Brings SHO channels to a common background, without erasing what sets them apart.
keywords: [SHO, HOO, narrowband, normalization, sky background, palette, Hubble]
related: [NBRGBCombination, LinearFit, ChannelCombination, BackgroundNeutralization]
icon: adjustments
references:
  - "PixInsight — NarrowbandNormalization script."
---

## Summary

Three narrowband filters acquired separately share neither sky background nor apparent gain. The
resulting palette is then dominated by those differences — one channel drives the colour because
its background sits higher, not because it carries more signal.

`NarrowbandNormalization` aligns each channel onto a reference channel, **on background pixels
only**.

## Why the background, and only the background

A fit over the whole image would be dragged by the emission regions — which are precisely what
we want to **differ** between channels. Aligning Hα onto OIII everywhere would erase what we are
trying to show.

Background pixels are designated by the **multiresolution support**, the very one used to
measure noise ([NoiseEvaluation](retina-doc://NoiseEvaluation)): background is what is
significant at none of the fine scales, **in all channels at once**. All of them, not each its
own: a fit is made on *common* pixels, otherwise you compare two different populations and the
resulting line means nothing.

## The degenerate case, which does happen

If the background is **perfectly flat** — synthetic image, or heavily denoised — the line is
undefined: its slope would depend on numerical noise alone. We then fall back on the **offset**,
which always is defined. Doing nothing would be worse: the process would appear to run without
acting, which is the hardest failure to diagnose.

## Two possible inputs

- **Mono set**: three named views (`red_view`, `green_view`, `blue_view`), one per filter. All
  three, or none — the process refuses a mixture.
- **Already-composed colour image**: with no named view, the image's own three channels are
  normalized against each other.

## Parameters

- **`reference`** — *enum* `red` | `green` | `blue`, default `green`. The channel the others
  align onto; it is left unmodified.
- **`red_view`**, **`green_view`**, **`blue_view`** — *str*. All three views, or none.
- **`k_sigma`** — *real*, default `3.0`. Significance threshold defining the background.
- **`match_scale`** — *bool*, default `True`. Align scale as well as offset. At `False`, only
  backgrounds are aligned: each channel keeps its contrast intact, which is sometimes
  preferable — the relative gain of the filters is then information you may not want erased.

## Tips & pitfalls

> **Normalize before composing, not after.** Once the three channels are stacked into a colour
> image, a per-channel fit runs into the fact that the colour is already made.

- The reference channel is **unchanged**: pick the one you are happy with, often the one
  carrying the most signal.
- If one channel is markedly noisier than the others, `match_scale=True` will amplify its noise
  along with its signal. Denoise it first.

## See also

- [NBRGBCombination](retina-doc://NBRGBCombination) — inject a line into an RGB image.
- [ChannelCombination](retina-doc://ChannelCombination) — compose the colour image.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — neutralize the background
  cast, a complementary gesture.
- [NoiseEvaluation](retina-doc://NoiseEvaluation) — the same multiresolution support, serving
  noise measurement.

## References

- PixInsight — *NarrowbandNormalization* script.
