---
id: NBRGBCombination
category: ColorCalibration
title: Narrowband / RGB Combination
brief: Injects Ha, OIII or SII into a broadband RGB image, at a scale measured on the stars.
keywords: [Ha, OIII, SII, narrowband, RGB, combination, SHO, HOO, scale]
related: [NarrowbandNormalization, ChannelCombination, LinearFit, LRGBCombination]
icon: color-swatch
references:
  - "PixInsight — NBRGBCombination script."
---

## Summary

A narrowband image shows an emission line with a contrast broadband cannot reach: there, the
line is drowned in the continuum. `NBRGBCombination` injects that signal into the RGB channel of
your choice, without crushing what was already there.

Three steps:

1. **Bring the narrowband to the scale** of the target channel. The two images have no reason to
   share units — filters, exposure times and sky all differ.
2. **Take the excess**: what, after scaling, exceeds the channel. That is the line signal
   broadband does not see.
3. **Add a share of it**, set by `strength`.

Taking the excess rather than the whole image is what **preserves stars**: a star is bright in
both, so it does not exceed, and is not added a second time.

## The scale comes from the stars, and that is less obvious than it looks

Two plausible approaches fail, and they had to be seen failing.

**A pixel-wise regression** between the two images does not work: emission pixels have the
largest abscissas, hence the most leverage, and they drag the line to them. On a synthetic field
whose true scale was 0.5, a naive regression returns **0.042** — at which point the process
injects nothing at all.

**Iterative outlier clipping** makes it worse. Under an already-collapsed slope, it is the
*healthy* stars that have the largest residuals: clipping rejects them and keeps the emission.

What works is reasoning **per star**: sum each one's flux in both images, and take the **median**
of the ratios. A star sitting on the nebula gives an aberrant ratio, but it is only one point
among others — the median ignores it, where least squares obeyed it. On the same field, the
measured scale is **0.494** against 0.5.

It is also, quite simply, how two images are put on a common scale in astronomy.

The **offset** is set on the **sky background**: fixing scale and pedestal on the same points
would lift the sky over the whole image. Each where it is measurable.

## Parameters

- **`ha_view`**, **`oiii_view`**, **`sii_view`** — *str*. Identifiers of the views to inject. At
  least one is required; all three can be used together.
- **`ha_channel`**, **`oiii_channel`**, **`sii_channel`** — *enum* `red` | `green` | `blue`.
  Defaults `red`, `green`, `red` — the usual HOO/SHO palette.
- **`mode`** — *enum* `manual` | `bandwidth`, default `manual`.
  - `manual`: `strength` alone. This is the control you actually want, "how much Hα" being an
    aesthetic judgement rather than a physical quantity.
  - `bandwidth`: `strength` multiplied by the bandwidth ratio. Physically grounded, but
    **discreet** — a 7/100 ratio gives 7% of the excess. Worth knowing before being surprised.
- **`strength`** — *real*, default `0.5`, range `0`–`1`.
- **`nb_bandwidth`** / **`rgb_bandwidth`** — *real*, defaults `7.0` / `100.0` nm. Used in
  `bandwidth` mode only.

## Tips & pitfalls

> **The images must be registered.** The process checks geometry and refuses rather than
> silently cropping, but it cannot see a one-pixel shift — which would leave coloured fringes
> at star edges.

- Inject **before** stretching, on linear data: that is where the scale relation between the
  two images is a simple proportion.
- If your field has too few stars (fewer than five measurable), the scale cannot be determined
  and the narrowband is taken as is: the result will be dominated by the gain difference.
  Widen the field or scale the images yourself.
- For a full SHO palette, first run the three channels through
  [NarrowbandNormalization](retina-doc://NarrowbandNormalization).

## See also

- [NarrowbandNormalization](retina-doc://NarrowbandNormalization) — bring three SHO channels to
  a common background before composing.
- [ChannelCombination](retina-doc://ChannelCombination) — compose a colour image from three
  views, with no notion of excess.
- [LinearFit](retina-doc://LinearFit) — the bare linear fit, if you prefer driving it yourself.

## References

- PixInsight — *NBRGBCombination* script.
