---
id: RGBWorkingSpace
category: ColorSpaces
title: RGB Working Space
brief: Renormalizes each RGB channel's gain from relative luminance weights, PixInsight-style RGBWS.
keywords: [RGBWS, luminance weights, color balance, Rec.709, RGB channels, per-channel gain]
related: [ColorCalibration, SCNR, ColorSaturation, LinearFit]
icon: color-swatch
references:
  - "PixInsight — RGBWorkingSpace process reference."
  - "ITU-R BT.709 — relative R/G/B luminance coefficients."
---

## Summary

`RGBWorkingSpace` models PixInsight's RGB working space in a minimal way: it takes three
**luminance weights** (one per Red/Green/Blue channel) and uses them to **rebalance the gain
of each channel**. Unlike PixInsight, where RGBWS just attaches weighting coefficients that
other tools reuse (luminance computation, SCNR, and so on), this Retina version **applies
the rebalancing directly to the pixels** — a pragmatic shortcut until the pipeline carries a
weight metadata shared across processes.

## Use cases

- **Simulate an alternative weighting convention** (Rec.709, Rec.601, equal-energy…) before
  luminance-sensitive treatments (`SCNR`, `ColorSaturation`, structure-aware noise reduction)
  to see how their result would change with a different definition of the "dominant" Green
  channel.
- **Correct a global channel imbalance** by giving more weight to the weakest channel and less
  to the strongest one — a quick, coarse adjustment, not to be confused with real colorimetric
  calibration.
- **Teaching / experimentation**: visualize concretely the effect of changing the RGB
  weighting on a real image, before more refined luminance-dependent tools are implemented.

## How it works

1. If the image has fewer than 3 channels (monochrome), it is returned unchanged (a copy).
2. The three weights `rw`, `gw`, `bw` are **normalized** to sum to 1 (falling back to 1.0 if
   the sum is zero, to avoid a division by zero).
3. Each normalized weight is multiplied by 3, giving a **per-channel gain** whose sum is
   always 3 (average gain = 1): it is this ×3 factor that makes the result neutral when the
   three weights are equal.
4. Each channel is multiplied by its gain, then the result is **clipped** to `[0, 1]` and cast
   back to `float32`.

## Mathematics

Let $w = (r_w, g_w, b_w)$ be the supplied weights and $S = r_w + g_w + b_w$ (with
$S \leftarrow 1$ if $S = 0$). The normalized weights and per-channel gains are:

$$ \tilde{w}_c = \frac{w_c}{S}, \qquad g_c = 3\,\tilde{w}_c, \qquad c \in \{R, G, B\}. $$

By construction $\sum_c g_c = 3$, so the average gain is always $1$. The output image is:

$$ I'_c(x,y) = \operatorname{clip}\big(I_c(x,y)\cdot g_c,\; 0,\; 1\big). $$

The neutral case ($I' = I$) corresponds exactly to $\tilde{w}_R = \tilde{w}_G = \tilde{w}_B =
\tfrac{1}{3}$, i.e. weights that are **equal to one another**, whatever their common absolute
value (since they get renormalized). Any deviation of one weight from the other two produces
a proportional amplification (relative weight > 1/3) or attenuation (relative weight < 1/3)
of the corresponding channel.

## Parameters

- **`rw`** — *real*, default `0.2126`, range `0`–`1`. Relative luminance weight of the Red
  channel (default value = Rec.709 coefficient).
- **`gw`** — *real*, default `0.7152`, range `0`–`1`. Relative luminance weight of the Green
  channel (default value = Rec.709 coefficient).
- **`bw`** — *real*, default `0.0722`, range `0`–`1`. Relative luminance weight of the Blue
  channel (default value = Rec.709 coefficient).

## Tips & pitfalls

> **Warning** — the default values (`0.2126 / 0.7152 / 0.0722`) are the Rec.709 coefficients,
> but **they are not equal to one another**: running the process with these default settings
> is **not neutral**. With these weights the effective gain is $g_R \approx 0.64$,
> $g_G \approx 2.15$, $g_B \approx 0.22$ — the image turns noticeably green. For a neutral
> pass, set all three weights to the **same value** (e.g. `rw = gw = bw = 0.333`).

- This is **not** a colorimetric calibration tool (see `ColorCalibration` or
  `SpectrophotometricColorCalibration` for real calibration against star catalogs): the
  weights here are chosen by hand, with no photometric reference.
- Since the gains are applied per channel independently, an existing color cast (light
  pollution, an uncalibrated filter) will be amplified if its channel receives a high weight.
- Prefer working on a linear, unstretched image: on an already-stretched image, rebalancing
  the gain also shifts the perceived black point of each channel.

## See also

- [ColorCalibration](retina-doc://ColorCalibration) — colorimetric calibration against reference stars.
- [SCNR](retina-doc://SCNR) — selective removal of the green color cast.
- [ColorSaturation](retina-doc://ColorSaturation) — saturation adjustment by hue.
- [LinearFit](retina-doc://LinearFit) — linear channel fit against a reference.

## References

- PixInsight — *RGBWorkingSpace* process reference.
- ITU-R BT.709 — relative R/G/B luminance coefficients.
