---
id: B3Estimator
category: ColorCalibration
title: B3 Estimator — Continuum Subtraction
brief: Isolates emission-line signal (e.g. H-alpha) by subtracting a scaled broadband continuum, with the scale factor k estimated robustly.
keywords: [H-alpha, continuum, narrowband, subtraction, emission line, sigma-clipping, nebula]
related: [PixelMath, LinearFit, StarAlignment, ChannelCombination]
icon: database
references:
  - "PixInsight — B3Estimator process reference (continuum subtraction)."
  - "astropy.stats.sigma_clipped_stats — robust location/scale estimation via iterative sigma-clipping."
---

## Summary

`B3Estimator` reproduces the idea of PixInsight's `B3Estimator`: combine two images of the same
field — a **narrowband** exposure (e.g. H-alpha) and a **broadband reference** ("continuum",
e.g. red or luminance) — to **isolate the line signal**. The continuum, scaled by a factor `k`,
is subtracted from the narrowband image: stars and background largely cancel out, leaving only
the emission excess proper to the line. `k` can be set manually or estimated automatically as a
robust (sigma-clipped) median ratio over the continuum's bright regions.

## Use cases

- **Isolate pure H-alpha emission** from a narrowband image by comparing it to a nearby
  continuum filter, producing a line map free of the broadband stellar contribution.
- **Boost nebular sharpness**: stars, dominated by the continuum, largely disappear after
  subtraction, leaving mostly emissive nebulosity.
- **Prepare an "H-alpha boost" layer** to blend back into the red channel of an LRGB image via
  `PixelMath`, for HOO/SHO/HaRGB-style renderings.
- **Manually calibrate `factor`** when auto-estimation fails (star-poor field, saturation,
  mismatched continuum filter).

## How it works

The process operates on the **active view** (the narrowband image) and references a second view
by name through the `continuum` parameter. Both images are first reduced to a monochrome
intensity (channel mean if the image is color). The continuum is then analyzed with
sigma-clipping to locate its bright pixels (stars + structured background), which anchor the
estimate of the scale ratio `k` between the two bands — unless `factor` is set explicitly
(`> 0`), in which case that supplied `k` is used as-is. The scaled continuum is then subtracted
from the narrowband image, a pedestal is added to avoid a negative background, and the result is
clipped to `[0, 1]`.

> **Note** — if `continuum` is empty, does not match any existing view, or has dimensions
> different from the active view, the process is a **silent no-op**: it returns an unchanged
> copy of the pixels, without raising an error. Double-check the exact continuum view name.

The effective `k` factor used (supplied or estimated) is stored in the instance's `.k` attribute
after execution — handy from a script to inspect it or reuse it on another view.

## Mathematics

Let $N(x,y)$ be the narrowband intensity (active view, averaged over channels if color) and
$C(x,y)$ the continuum's (`continuum`), sampled on the same pixel grid. If `factor` = 0 (auto
mode), the continuum's robust statistics are first computed via iterative sigma-clipping
($\sigma = 3$):

$$ \tilde C = \operatorname{med}_\sigma(C), \qquad \sigma_C = \operatorname{std}_\sigma(C) $$

The mask of "reference" pixels — essentially stars and bright continuum — is defined as:

$$ M = \{(x,y) \;:\; C(x,y) > \tilde C + \sigma_C\} $$

Over this mask, the pixelwise ratio $r(x,y) = N(x,y) / \max(C(x,y),\, 10^{-6})$ is computed, and
the retained scale factor is its **median**:

$$ k = \operatorname{med}_{(x,y)\in M}\; r(x,y) $$

The underlying assumption is that these bright pixels are mostly stars whose flux in the
narrowband and continuum images is proportional with the same ratio `k` — so their subtraction
should cancel out. If `factor` > 0, this estimation step is skipped and $k = \texttt{factor}$
directly.

The final result is:

$$ E(x,y) = \operatorname{clip}\big(N(x,y) - k\,C(x,y) + p,\; 0,\; 1\big), \qquad p = \texttt{pedestal} $$

If the input image has multiple channels, $E$ (monochrome) is **replicated identically** across
each of them.

## Parameters

- **`continuum`** — *str*, default `""`. Name of the continuum (broadband) view to subtract from
  the active view. Must reference an existing view of matching dimensions; otherwise the process
  does nothing (see note above).
- **`factor`** — *real*, default `0.0`, range `0`–`100`. Scale factor `k` applied to the
  continuum before subtraction. `0` triggers automatic estimation via a sigma-clipped median
  ratio; any value `> 0` sets `k` manually and disables the estimation.
- **`pedestal`** — *real*, default `0.05`, range `0`–`1`. Additive offset applied after
  subtraction, to keep the background (where $N \approx k\,C$) from falling to zero or negative
  and being clipped.

## Tips & pitfalls

> **Warning** — the two views must be **perfectly pixel-aligned** (same dimensions, same
> sampling). `B3Estimator` performs no registration: run `StarAlignment` beforehand if the
> images come from different exposures/instruments.

- The result is **monochrome** (channel mean), replicated across all output channels even if the
  input image was in color: original color information on this view is lost.
- Automatic `k` estimation assumes a field rich enough in stars to anchor the ratio. On a field
  dominated by a large galaxy or extended nebulosity (few isolated stars in the mask), the
  auto ratio can be biased — set `factor` manually after a first visual estimate.
- Always work on **linear** data (before any stretch): the proportional relationship between
  bands assumes a linear sensor response.
- The process is maskable: apply a star or region mask to protect specific areas from the
  subtraction if needed.

## See also

- [PixelMath](retina-doc://PixelMath) — free combination of channels/views, a general
  alternative to a fixed continuum subtraction.
- [LinearFit](retina-doc://LinearFit) — linear fit of a view onto a reference, a principle close
  to the estimation of `k`.
- [StarAlignment](retina-doc://StarAlignment) — prior registration, essential if the two bands
  are not already pixel-aligned.
- [ChannelCombination](retina-doc://ChannelCombination) — recombine the isolated line into a
  color composition (HOO, SHO, HaRGB…).

## References

- PixInsight — *B3Estimator* process reference (continuum subtraction).
- astropy.stats — *sigma_clipped_stats*, robust location/scale estimation via iterative
  sigma-clipping.
