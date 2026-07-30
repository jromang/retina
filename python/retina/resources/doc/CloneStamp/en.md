---
id: CloneStamp
category: Painting
title: Clone Stamp
brief: "Copies a disc of pixels (source → destination) with a feathered edge."
keywords: [clone stamp, retouching, cloning, alpha blending, artifact, blending]
related: [SeamlessClone, Inpaint, CosmeticCorrection, PixelMath]
icon: rubber-stamp
references:
  - "PixInsight — CloneStamp process reference."
  - "Alpha blending / feathering — weighted linear blend at edges."
---

## Summary

`CloneStamp` copies a disc of pixels from a **source area** to a **destination area**,
feathering the seam with an alpha gradient at the disc's edge. It is the scriptable, replayable
core of the clone-stamp tool: where PixInsight's GUI tool is a continuous mouse gesture, here
every "stamp" is an explicit operation (integer coordinates, radius, softness) that gets logged
in the history and can be chained in a script to reconstruct a full retouching gesture.

## Use cases

- **Erase an isolated satellite trail, plane trail or cosmic ray** by copying a patch of nearby
  sky background over the defect.
- **Hide a sensor artifact** (a small cluster of hot pixels, a localized defective column, an
  optical reflection) not covered by `CosmeticCorrection` (which operates pixel by pixel, not
  by patch).
- **Visually rebuild** a small region (mosaic seam, field edge) by drawing from an area of
  similar texture elsewhere in the same image.
- **Script a reproducible retouching sequence**: a Python script chains several `CloneStamp`
  calls with precise coordinates, replayable on a recalibrated image.

## How it works

The operator works over a square neighborhood of side `2·radius + 1`, centered alternately on
the source and the destination:

1. For each offset `(dx, dy)` within that square, compute the **radial distance** to the
   center of the disc.
2. Derive an **alpha weight** that is 1 at the center and decreases linearly to 0 as it
   approaches the disc's edge, over a transition width proportional to `softness` (0 = hard cut
   at `radius`, 1 = gradient spanning the whole disc).
3. The destination pixel is replaced by a **linear blend** (alpha blending) between its
   original value and the corresponding source pixel's value, weighted by that alpha.
4. Pixel pairs whose source **or** destination fall outside the image are skipped (the
   destination pixel then keeps its original value) — no out-of-bounds access, no wraparound.

A single instance can carry a whole **stroke**: `points` lists the successive destination
positions of the gesture, `[x0, y0, x1, y1, …]`. The source-to-destination offset is then
*constant*, taken from the first point (`src − (x0, y0)`), so the sampled area follows the
brush — the classic clone-stamp semantics. Every point is stamped onto the image **already
modified** by the previous ones, so a stroke of N points yields exactly the same result as N
chained single-disc instances, including when it runs back over its own source area. It only
costs one history entry, though, which is the right granularity for a gesture — you want to
undo *a stroke*, not fifty discs.

The result is a disc of source pixels "pasted" onto the destination, with a feathered rather
than a hard-cut edge, which reduces the visibility of the seam on a roughly uniform background
(sky background, diffuse nebulosity). For structured backgrounds where even a feathered edge
leaves a visible seam, prefer `SeamlessClone`, which blends **gradients** (Poisson blending)
instead of raw pixel values.

## Mathematics

Let $r$ = `radius`, $(x_s, y_s)$ the source center, $(x_d, y_d)$ the destination center, and
$I$ the input image. For every integer offset $(dx, dy)$ with $-r \le dx, dy \le r$, define the
distance to the disc's center:

$$ d(dx, dy) = \sqrt{dx^2 + dy^2} $$

and the width of the transition zone, proportional to the radius:

$$ w = \max(\texttt{softness},\, \varepsilon)\cdot r $$

The blend weight (1 at the center, 0 beyond the disc) is:

$$ \alpha(d) = \operatorname{clip}\!\left(\frac{r - d}{w},\; 0,\; 1\right) $$

The destination pixel is updated by linear interpolation between its original value and the
source pixel value at the same offset:

$$ I'(x_d + dx,\, y_d + dy) = \big(1 - \alpha(d)\big)\, I(x_d + dx,\, y_d + dy)
   \;+\; \alpha(d)\, I(x_s + dx,\, y_s + dy) $$

for every coordinate pair that stays inside the image; otherwise the destination pixel is left
unchanged. As `softness → 0`, $w$ tends to a negligible $\varepsilon$ and $\alpha(d)$ switches
almost abruptly from 1 to 0 at $d = r$: the disc becomes a hard-edged stencil. When
`softness = 1`, $w = r$ and $\alpha$ decreases **linearly** over the whole radius, from the
center ($\alpha=1$) to the edge ($\alpha=0$): the feather is at its widest.

## Parameters

- **`src_x`** — *int*, default `0`, range `0`–`1000000`. X coordinate (pixels) of the center of
  the source area to copy from.
- **`src_y`** — *int*, default `0`, range `0`–`1000000`. Y coordinate (pixels) of the source
  area's center.
- **`dst_x`** — *int*, default `0`, range `0`–`1000000`. X coordinate (pixels) of the center of
  the destination area to overwrite.
- **`dst_y`** — *int*, default `0`, range `0`–`1000000`. Y coordinate (pixels) of the
  destination area's center.
- **`radius`** — *int*, default `8`, range `1`–`1000`. Radius (pixels) of the copied disc. Must
  cover the defect to hide with some margin, without eating into nearby useful signal.
- **`softness`** — *real*, default `0.3`, range `0.0`–`1.0`. Relative width of the gradient at
  the disc's edge: `0` = hard cut, `1` = linear feather over the whole radius. An intermediate
  value (0.2–0.4) is usually enough to make the seam invisible on a calm background.
- **`points`** — *floatlist*, default empty. Stroke trajectory: a flat list of **destination**
  positions, `[x0, y0, x1, y1, …]`, in pixels. Empty, the process falls back to the single stamp
  described by `dst_x`/`dst_y`. Non-empty, `dst_x`/`dst_y` only serve to set the source offset,
  measured on the first point. There is deliberately no spacing parameter: the process stamps
  the points it is given, and it is up to the caller (the tool, or your script) to sow them —
  a quarter of the radius gives a smooth stroke without multiplying stamps.

## Tips & pitfalls

> **Warning** — if the source or destination area partly extends past the image edges, the
> operation **is skipped entirely** for the affected offsets (neither the out-of-bounds source
> nor destination is processed): the result can look like it is "missing" a crescent of the
> disc. Make sure `radius` leaves enough margin from the image borders.

- Pick a **source** with texture and background level similar to the destination:
  `CloneStamp` performs a plain value blend, with no colorimetric adaptation.
- On a strongly structured background (bright nebulosity, marked gradient), a feathered edge
  may not be enough to hide the seam; use `SeamlessClone`, which blends gradients rather than
  raw values.
- For very numerous, tiny point defects (scattered hot pixels), `CosmeticCorrection` is more
  appropriate and faster than chaining many `CloneStamp` calls.
- For a dragged "stamp stroke", use `points` rather than a stack of instances: same result to
  the pixel, a single history entry, and a far lower cost (the alpha kernel is computed once for
  the whole stroke).

## See also

- [SeamlessClone](retina-doc://SeamlessClone) — invisible-seam cloning via Poisson blending,
  for structured backgrounds.
- [Inpaint](retina-doc://Inpaint) — fill-in by gradient propagation from a mask map, with no
  explicit source area.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — pixel-by-pixel correction of sensor
  defects (hot/cold pixels, columns).
- [PixelMath](retina-doc://PixelMath) — arbitrary expressions for more general retouching.

## References

- PixInsight — *CloneStamp* process reference.
- Alpha blending / feathering — weighted linear blend at edges.
