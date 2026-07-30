---
id: LarsonSekanina
category: Convolution
title: Larson-Sekanina Filter
brief: "Rotational gradient filter I − ½·(rot(+α) + rot(−α)) about a center, revealing cometary jets."
keywords: [comet, jets, rotational gradient, coma, asymmetry, enhancement, nucleus]
related: [CometAlignment, RadialProfileMeasurement, RickerWaveletEnhance, UnsharpMask]
icon: windmill
references:
  - "Larson, S. M. & Sekanina, Z. (1984) — Coma morphology and dust-emission pattern of periodic comet Halley. Astronomical Journal, 89, 571."
  - "PixInsight — LarsonSekanina tool reference."
  - "scikit-image — skimage.transform.rotate."
---

## Summary

`LarsonSekanina` is the classic **rotational gradient filter** used in cometary imaging: it
brings out the **jets and asymmetric structures** in a comet's coma by removing, at every
pixel, the **centrally symmetric component** of the signal. The image is compared to the
average of two copies of itself rotated by `+angle` and `-angle` degrees about a center (by
default the geometric center of the image, but in practice the comet's nucleus/photocenter).
Anything **invariant under rotation** — the diffuse, roughly symmetric coma — cancels out in
the subtraction; anything that **depends on angle** — jets, fans, spiral structures — stands
out in light and dark.

## Use cases

- **Reveal dust/gas jets** of a comet, invisible in the raw image because they are drowned in
  the coma's brightness, which falls off steeply toward the nucleus.
- **Study nucleus rotation**: spiral jets and their evolution frame to frame give clues about
  the nucleus's rotation period and activity.
- **Compare several angle steps** (small vs. large `angle`) to separate fine structures near
  the nucleus from broad structures in the outer coma.
- Typically used downstream of `CometAlignment` (nucleus-centered stacking) and a precise
  photocenter fix before filtering.

## How it works

1. The rotation center is set by `cx`/`cy`, or defaults to the image's geometric center
   (`(w-1)/2, (h-1)/2`) — in practice it should be placed on the **nucleus's photocenter**.
2. For each channel, the image is rotated twice about that center with
   `skimage.transform.rotate` (bilinear interpolation, `edge` border mode): once by
   `+angle` degrees, once by `-angle` degrees.
3. Averaging the two rotations estimates the **local symmetric component** of the signal about
   the center (what the coma would look like if it rotated without changing shape).
4. That average is subtracted from the original image: the result is zero wherever the signal
   is locally symmetric under rotation, and non-zero wherever a structure breaks that symmetry
   (jet, fan, condensation).
5. The result, theoretically centered on 0, is **re-centered around 0.5** and clipped to
   `[0, 1]` so it stays displayable as an ordinary image (structure-free zones appear mid-gray,
   jets appear bright or dark depending on the sign of the gradient).

## Mathematics

Let $I(x, y)$ be a channel's image and $R_\theta$ the rotation operator by angle $\theta$
about the center $(c_x, c_y)$ (bilinear interpolation). The filter computes:

$$ G(x, y) = I(x, y) \;-\; \frac{1}{2}\Big( R_{+\alpha}[I](x, y) + R_{-\alpha}[I](x, y) \Big) $$

where $\alpha$ is the `angle` parameter. The term
$\tfrac{1}{2}\big(R_{+\alpha}[I] + R_{-\alpha}[I]\big)$ is a local estimate of the part of $I$
that is **invariant under rotation by $\pm\alpha$**: if $I$ has perfect rotational symmetry
about the center, then $R_{+\alpha}[I] = R_{-\alpha}[I] = I$ and $G \equiv 0$. Conversely, a
structure located at some radial distance $r$ from the center and a given azimuthal angle gets
angularly shifted in $R_{\pm\alpha}[I]$; the subtraction reveals a **signed doublet** (a
positive edge on one side, negative on the other) whose amplitude grows with the local
azimuthal gradient of $I$ and with $\alpha$ for small angles.

The displayed image is finally:

$$ I'(x, y) = \operatorname{clip}\big(G(x, y) + 0.5,\; 0,\; 1\big) $$

The $0.5$ offset re-centers zero (no structure) on mid-gray, so both excesses (jets, brighter)
and deficits (shadows, darker) around the photocenter are readable.

## Parameters

- **`angle`** — *real*, default `5.0`, range `0.1`–`45`. Rotational angle `α` in degrees used
  for the `+α`/`-α` rotation pair. Small angle → sensitive to fine structures close to the
  center; large angle → reveals broader structures but blurs fine detail and can introduce
  interpolation artifacts near the edges.
- **`cx`** — *real*, default `-1.0`, range `-1`–`1,000,000`. X coordinate of the rotation
  center in pixels. The special value `-1` means "image midpoint" (`(width-1)/2`).
- **`cy`** — *real*, default `-1.0`, range `-1`–`1,000,000`. Y coordinate of the rotation
  center in pixels. The special value `-1` means "image midpoint" (`(height-1)/2`).

## Tips & pitfalls

> **Warning** — the result depends **strongly** on the accuracy of the center `(cx, cy)`. A
> center offset by even a few pixels from the true nucleus photocenter introduces a spurious
> gradient that masks the real jets. Measure the nucleus centroid (e.g. with
> `RadialProfileMeasurement` or a source detection) before applying the filter.

> **Note** — the output image is **not** a photometric image: it is meant for visual diagnosis
> of morphological structure, not flux measurement.

- Prefer working on an already-stretched image (STF or `HistogramTransformation`) centered on
  the coma, otherwise rotation artifacts at the borders dominate the result.
- Try several `angle` values (e.g. 5°, 15°, 30°): fine and broad structures do not show up at
  the same angle.
- If the comet is off-center in the frame, crop first (`Crop`/`DynamicCrop`) so the default
  center (`cx = cy = -1`) roughly coincides with the nucleus, or set `cx`/`cy` explicitly.
- The filter is applied channel by channel; on a color image, consider working on a grayscale
  (luminance) version to avoid chromatic artifacts along jet edges.

## See also

- [CometAlignment](retina-doc://CometAlignment) — nucleus-centered stacking, useful upstream to
  get a sharp coma before filtering.
- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — radial profile
  measurement, useful to pinpoint the photocenter.
- [RickerWaveletEnhance](retina-doc://RickerWaveletEnhance) — multiscale wavelet enhancement,
  complementary for bringing out fine structures.
- [UnsharpMask](retina-doc://UnsharpMask) — local-contrast enhancement via blurred mask,
  another technique for highlighting fine structures.

## References

- Larson, S. M. & Sekanina, Z. (1984) — *Coma morphology and dust-emission pattern of periodic
  comet Halley*. Astronomical Journal, 89, 571.
- PixInsight — *LarsonSekanina* tool reference.
- scikit-image — *skimage.transform.rotate*.
