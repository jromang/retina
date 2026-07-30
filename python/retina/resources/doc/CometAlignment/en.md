---
id: CometAlignment
category: ImageRegistration
title: Comet Alignment
brief: Stacks frames by compensating the comet nucleus's linear proper motion, keeping the comet sharp while the stars trail.
keywords: [comet, alignment, stacking, linear shift, cometary nucleus, registration, proper motion]
related: [LarsonSekanina, StarAlignment, Integration, PhaseCorrelationAlignment]
icon: comet
references:
  - "PixInsight — CometAlignment tool reference."
  - "scipy.ndimage.shift — spline interpolation for sub-pixel shifting."
---

## Summary

`CometAlignment` is a **global** process that stacks a series of frames by following the
**comet nucleus's proper motion** instead of the star field. A comet moves against the sky
background from one exposure to the next (real orbital motion), at a near-constant apparent
rate over the span of a session: compensating that linear displacement before averaging keeps
the nucleus and coma sharp, at the cost of trailing the stars. It is the exact opposite of
`StarAlignment`, which freezes the stars and lets the comet trail.

## Use cases

- **Isolate a comet** in a star-dense field, revealing the coma and jets without it being
  buried in the noise of a single exposure.
- **Combine with a classic star-aligned stack**: produce a "sharp comet / trailed stars" image
  and a "sharp stars / trailed comet" image, then merge them (mask, `PixelMath`) for a result
  clean on both fronts.
- **Measure or confirm** a comet's apparent velocity by adjusting `vx/vy` until the nucleus
  looks point-like on the stack.

## How it works

1. The frames listed in `frames` are loaded **in chronological order** (list order drives the
   index `i = 0, 1, 2, …` used below).
2. Each frame `i` is shifted by `(-i·vx, -i·vy)` pixels (bilinear interpolation, zero fill
   outside the frame): frame `0` acts as the stationary reference, and later frames are pulled
   back proportionally to their rank, cancelling out the nucleus's motion assumed to be linear
   and uniform between consecutive exposures.
3. The shifted frames are **simply averaged** (no sigma rejection here, unlike `Integration`)
   to produce the final image, published in a new window named `new_image_id`.

The shift compensates for the comet's motion, so the stars — stationary in the sensor's
reference frame — end up displaced by a growing amount from one frame to the next: they appear
as trails in the result, while the cometary nucleus stays superimposed on itself.

## Mathematics

Let $I_i(x,y)$ be the frame of index $i \in \{0,\dots,N-1\}$ (chronological order of `frames`),
and $(v_x, v_y)$ the nucleus's apparent velocity in pixels/frame (`vx`, `vy`). The model assumes
**linear, uniform motion**: the nucleus's position at frame $i$ differs from its position at
frame $0$ by $(i\,v_x,\, i\,v_y)$ pixels.

Each frame is registered by interpolation (order-1 spline, constant zero fill), using a shift
vector $(-i\,v_x, -i\,v_y)$ that cancels the nucleus's assumed displacement and brings it back
to its position in $I_0$:

$$ J_i(x, y) = I_i\big(x + i\,v_x,\; y + i\,v_y\big). $$

The output image is the **plain average** of the registered frames:

$$ C(x,y) = \frac{1}{N} \sum_{i=0}^{N-1} J_i(x,y). $$

The nucleus, now superimposed on itself across all frames, gains signal-to-noise ratio like a
classic integration ($\propto \sqrt{N}$). A fixed field star, on the other hand, lands at a
different position in each $J_i$ (offset by $i\,(v_x, v_y)$ from its original position): its
light is smeared over a trail roughly $(N-1)\,\|(v_x,v_y)\|$ pixels long, diluting its peak
intensity accordingly.

## Parameters

- **`frames`** — *pathlist*, default `[]`. List of image files to stack, **in chronological
  acquisition order** (the list index directly drives the shift computation).
- **`vx`** — *real*, default `0.0`, range `-1000`–`1000`. Nucleus's apparent velocity along X,
  in pixels per frame.
- **`vy`** — *real*, default `0.0`, range `-1000`–`1000`. Nucleus's apparent velocity along Y,
  in pixels per frame.
- **`new_image_id`** — *str*, default `"comet"`. Identifier of the window created to hold the
  stacking result.

## Tips & pitfalls

> **Warning** — the order of `frames` **is** the process's clock: swapping two exposures or
> mixing non-contiguous sessions completely throws off the applied shift, even with a correct
> `vx/vy`.

> **Note** — `vx`/`vy` left at `0.0` (the defaults) reduces to a plain stack with no
> registration at all: useful to first check star trailing before estimating the nucleus's
> velocity.

- Estimate `vx/vy` by measuring the nucleus's position (e.g. via `DynamicPSF` or a manual pick)
  on the first and last frame, then dividing the total displacement by `N - 1`.
- Unlike `Integration`, there is **no outlier rejection**: a satellite trail or cosmic ray
  crossing a single frame remains visible (only attenuated by the $1/N$ factor).
- To combine a sharp comet and sharp stars in a single image, produce both stacks (this one,
  plus a classic `StarAlignment` + `Integration`) and blend them under a mask.

## See also

- [LarsonSekanina](retina-doc://LarsonSekanina) — rotational gradient filter to reveal jets and
  coma structures once the comet is isolated.
- [StarAlignment](retina-doc://StarAlignment) — classic star-based alignment (this process's
  functional opposite).
- [Integration](retina-doc://Integration) — stacking with robust sigma rejection, to use
  downstream on the star-aligned frames.
- [PhaseCorrelationAlignment](retina-doc://PhaseCorrelationAlignment) — global, star-free
  registration, useful to estimate an offset between two exposures.

## References

- PixInsight — *CometAlignment* tool reference.
- scipy.ndimage.shift — spline interpolation for sub-pixel shifting.
