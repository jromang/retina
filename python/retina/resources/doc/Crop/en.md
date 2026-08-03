---
id: Crop
category: Geometry
title: Crop
brief: Crops the image to a rectangle defined by fractional [0,1] bounds of the frame.
keywords: [crop, cropping, geometry, framing, borders, trim]
related: [DynamicCrop, Resample, IntegerResample, Rotation]
icon: crop
references:
  - "PixInsight — Crop tool reference."
  - "scikit-image / numpy — 2D/3D array slicing."
---

## Summary

`Crop` trims the image down to a **rectangle** defined by four **fractional** bounds in
`[0, 1]`: `x0`/`y0` set the top-left corner of the kept area, `x1`/`y1` its bottom-right
corner. It is the "hard" cropping operator: the geometry changes and the result replaces the
active image (`is_maskable = False`, since a blend mask assumes an unchanged shape). Expressing
the bounds as frame fractions rather than pixels makes the setting resolution-independent —
useful for replaying the same crop on a differently resampled version of the same image.

![Before — Crop](figures/before.webp)
![After — Crop](figures/after.webp)

*The full frame, and the cropped rectangle. The two are deliberately different sizes — that is the process.*

## Use cases

- **Remove dirty edges** from an integrated stack (low-coverage areas, drizzle artifacts,
  registration fringes) before stretching.
- **Isolate a subject** (a galaxy, a region within a large nebula) for dedicated processing
  or a tightly framed final export.
- **Cut off residual vignetting** or poorly flat-corrected corners, when background
  correction alone is not enough.
- **Produce a quick preview thumbnail** (cropped inspection view) without setting up a
  temporary `Preview`.

## How it works

The four parameters are interpreted as **fractions of the active image's frame**: `x0`, `x1`
along the width, `y0`, `y1` along the height, with the origin `(0,0)` at the **top-left**
corner. The process converts these fractions into integer pixel indices via nearest rounding
(`round(f * dimension)`), then performs a plain numpy **array slice** over the first two axes
of `(H, W, C)`, keeping all channels.

Two safeguards make the operator tolerant of out-of-order input:

1. **Bound ordering** — `x0`/`x1` (and `y0`/`y1`) are automatically sorted via `min`/`max`, so
   swapping left/right or top/bottom in the UI does not raise an error.
2. **Minimum extent** — if the sorted bounds coincide (zero width or height after rounding),
   the upper bound is pushed out by at least one pixel, guaranteeing a non-empty output.

The resulting array is copied (`.copy()`) to detach it from the original buffer before it
replaces the pixels of the processed view.

## Mathematics

Let the image have dimensions $H \times W$ (height × width) and fractional bounds
$x_0, x_1, y_0, y_1 \in [0,1]$. The bounds are first ordered:

$$ \tilde{x}_0 = \min(x_0, x_1), \qquad \tilde{x}_1 = \max(x_0, x_1) $$

and likewise for $\tilde{y}_0, \tilde{y}_1$. Pixel indices follow by rounding:

$$ i_0 = \operatorname{round}(\tilde{y}_0 \cdot H), \quad i_1 = \max\!\big(\operatorname{round}(\tilde{y}_1 \cdot H),\, i_0 + 1\big) $$

$$ j_0 = \operatorname{round}(\tilde{x}_0 \cdot W), \quad j_1 = \max\!\big(\operatorname{round}(\tilde{x}_1 \cdot W),\, j_0 + 1\big) $$

The output image $I'$, of size $(i_1 - i_0) \times (j_1 - j_0)$, is simply the restriction of
$I$ to that rectangle, channel by channel:

$$ I'(y, x, c) = I(y + i_0,\; x + j_0,\; c) \qquad \text{for } 0 \le y < i_1-i_0,\ 0 \le x < j_1-j_0 $$

No interpolation is involved: each output pixel is an exact copy of one input pixel, so the
operator is **lossless** over the retained area (unlike `Resample`, which resamples).

## Parameters

- **`x0`** — *real*, default `0.0`, range `0`–`1`. **Left** edge of the kept area, as a
  fraction of width (`0` = image's left edge).
- **`y0`** — *real*, default `0.0`, range `0`–`1`. **Top** edge of the kept area, as a
  fraction of height (`0` = image's top edge).
- **`x1`** — *real*, default `1.0`, range `0`–`1`. **Right** edge of the kept area, as a
  fraction of width (`1` = image's right edge).
- **`y1`** — *real*, default `1.0`, range `0`–`1`. **Bottom** edge of the kept area, as a
  fraction of height (`1` = image's bottom edge).

## Tips & pitfalls

> **Warning** — `Crop` is **destructive** and resizes the image: pixels outside the rectangle
> are permanently discarded from the view's history (though `undo()` remains available until
> the view is re-saved). Check the framing on a `Preview` before applying to the main view.

> **Note** — because the bounds are fractional, the same parameter set applied to two versions
> of an image at different resolutions (e.g. before/after `Resample`) crops the **same relative
> region**, not the same pixel count.

- To interactively drag out a crop rectangle with a live preview, use
  [DynamicCrop](retina-doc://DynamicCrop) instead, which combines cropping and rotation in a
  single pass.
- A crop drawn too tightly around an object hampers downstream processing that needs sky-
  background margin (noise measurement, `BackgroundExtraction`, alignment): keep a background
  border if a global process still has to run afterward.

## See also

- [DynamicCrop](retina-doc://DynamicCrop) — interactive crop combined with rotation.
- [Resample](retina-doc://Resample) — scale-factor resampling (with interpolation).
- [IntegerResample](retina-doc://IntegerResample) — integer-factor reduction/enlargement.
- [Rotation](retina-doc://Rotation) — rotation by an arbitrary angle.

## References

- PixInsight — *Crop* tool reference.
- scikit-image / numpy — 2D/3D array slicing.
