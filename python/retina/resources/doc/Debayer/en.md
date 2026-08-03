---
id: Debayer
category: Debayer
title: Debayer
brief: Reconstructs a color RGB image from a single-channel sensor filtered by a Bayer color filter array (CFA).
keywords: [debayer, CFA, Bayer pattern, demosaicing, RGGB, bilinear, Malvar]
related: [SplitCFA, MergeCFA, CosmeticCorrection, PixelInterpolation]
icon: grid-dots
references:
  - "colour-science/colour-demosaicing — demosaicing_CFA_Bayer_bilinear / Malvar2004."
  - "Malvar, H., He, L.-W., Cutler, R. — High-Quality Linear Interpolation for Demosaicing of Bayer-Patterned Color Images (2004)."
  - "Losson, O., Macaire, L., Yang, Y. — Comparison of Color Demosaicing Methods (2010)."
---

## Summary

`Debayer` turns a **single-channel raw frame** from a color sensor equipped with a Bayer color
filter array (CFA) into a **three-channel RGB** image, by interpolating each color plane's
missing values from neighboring pixels. It is the mandatory step between acquisition on a
one-shot-color (OSC) sensor — or a color camera not already debayered — and any downstream
color processing.

![Bayer mosaic — Debayer](figures/mosaic.webp)
![Reconstructed colour — Debayer](figures/debayered.webp)

*A Bayer mosaic and its reconstruction into full colour. The mosaic is built from the survey's own bands, the repository carrying no real one-shot-colour raw.*

## Use cases

- **First processing step** for a raw frame from a color camera (DSLR, OSC astro camera)
  before calibration or integration.
- **Reconstruct usable color** after a `MergeCFA` step that recombined monochrome sub-frames
  into a synthetic CFA mosaic.
- Visually compare the artifacts of **different interpolation methods** (`bilinear` vs
  `malvar`) on the same raw frame before locking in an acquisition pipeline.

## How it works

A CFA sensor measures **only one color per photosite**: red, green and blue pixels are
interleaved in a repeating $2\times2$ pattern (`pattern`: `RGGB`, `BGGR`, `GRBG` or `GBRG`).
The process first builds three **binary masks** $R_m$, $G_m$, $B_m$ marking, for each sensor
position, which channel was actually sampled, then fills in the two-thirds of each plane that
is missing through **spatial interpolation**:

- **`bilinear`** — convolution of the masked CFA plane with a dedicated $3\times3$ kernel per
  channel (weighted average of the immediate neighbors). Fast, but produces color fringing
  (*zippering*) along high-contrast edges.
- **`malvar`** (Malvar, He & Cutler 2004) — a bilinear-interpolation variant enriched with a
  **high-frequency correction term** derived from the green channel's gradients, which sharpens
  edges noticeably while remaining a simple linear filter (hence still fast).

If the image already has more than one channel (i.e. it is not a raw CFA frame), the process
is a **no-op**: the data is copied through unchanged. The output is always **clipped to
`[0, 1]`** and produced as `float32`.

## Mathematics

The CFA plane $C(x,y)$ is split according to the Bayer pattern into three sparse planes:

$$ R(x,y) = C(x,y)\cdot R_m(x,y), \quad G(x,y) = C(x,y)\cdot G_m(x,y), \quad B(x,y) = C(x,y)\cdot B_m(x,y) $$

where $R_m, G_m, B_m \in \{0,1\}$ are the complementary sampling masks
($R_m + G_m + B_m = 1$ everywhere). **Bilinear** interpolation applies a per-channel 2D
convolution:

$$ \hat{G} = G * H_G, \qquad H_G = \frac{1}{4}\begin{pmatrix}0&1&0\\1&4&1\\0&1&0\end{pmatrix},
\qquad
\hat{R} = R * H_{RB}, \; \hat{B} = B * H_{RB}, \qquad
H_{RB} = \frac{1}{4}\begin{pmatrix}1&2&1\\2&4&2\\1&2&1\end{pmatrix} $$

Green, sampled twice as densely in the Bayer pattern, uses a cross-shaped kernel; red and blue
use a full $3\times3$ kernel weighted by distance. The **Malvar** method reuses this scheme but
adds, for each missing channel, a correction proportional to the **local Laplacian** of an
already-known channel (typically green), of the form:

$$ \hat{C}(x,y) = \big(C * H_{\text{bilin}}\big)(x,y) \;+\; \alpha \cdot \nabla^2 G(x,y) $$

using $5\times5$ kernels whose coefficients $\alpha$ (taken from the original paper) exploit the
correlation between the three channels' high frequencies to reduce color aliasing at
essentially no extra computational cost compared to plain bilinear.

## Parameters

- **`pattern`** — *enum*, default `RGGB`, choices `RGGB`, `BGGR`, `GRBG`, `GBRG`. The sensor's
  CFA pattern, i.e. the $2\times2$ arrangement of red/green/blue filters as defined by the
  sensor manufacturer (check the camera documentation or the FITS `BAYERPAT` keyword). A wrong
  pattern yields an image with incoherent, one-pixel-shifted colors.
- **`method`** — *enum*, default `bilinear`, choices `bilinear`, `malvar`. Interpolation
  algorithm. `bilinear` is faster and softer (slightly blurred); `malvar` restores more fine
  detail at the cost of a slightly heavier computation and a higher risk of artifacts on noisy
  data.

## Tips & pitfalls

> **Warning** — a wrong `pattern` does not fail visibly: the colors are simply wrong and
> shifted by one pixel. Always check the pattern given by the sensor manufacturer or the FITS
> `BAYERPAT` keyword when in doubt.

> **Note** — on heavily noisy data (high gain, short exposures), the `malvar` method can
> amplify chroma noise by interpolating spurious gradients. A light denoise pass before
> debayering, or falling back to `bilinear`, limits this effect.

- Debayering should happen **before** histogram stretching but generally **after**
  bias/dark subtraction, on still-linear data.
- To inspect individual CFA channels without recombining them, see `SplitCFA`; to rebuild a
  synthetic CFA mosaic from sub-frames, see `MergeCFA`.

## See also

- [SplitCFA](retina-doc://SplitCFA) — splits a CFA frame into its four sub-channels without interpolation.
- [MergeCFA](retina-doc://MergeCFA) — recombines sub-frames into a synthetic CFA mosaic.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — hot/dead pixel correction, useful before or after debayering.
- [PixelInterpolation](retina-doc://PixelInterpolation) — generic interpolation schemes used elsewhere (resampling, alignment).

## References

- colour-science/colour-demosaicing — *demosaicing_CFA_Bayer_bilinear* / *Malvar2004*.
- Malvar, H., He, L.-W., Cutler, R. — *High-Quality Linear Interpolation for Demosaicing of Bayer-Patterned Color Images* (2004).
- Losson, O., Macaire, L., Yang, Y. — *Comparison of Color Demosaicing Methods* (2010).
