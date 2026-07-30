---
id: StarReduction
category: MaskGeneration
title: Star Reduction
brief: Shrinks the apparent size of stars without touching the rest, from a starless image.
keywords: [stars, reduction, starless, screen model, erosion, Blanshan, halo]
related: [StarRemoval, StarMask, MorphologicalTransformation, PixelMath]
icon: star
references:
  - "Bill Blanshan — PixelMath star reduction methods (principle reused here)."
---

## Summary

`StarReduction` reduces the apparent size or brightness of stars **without touching the rest of
the image**. Three methods, in the spirit of those Bill Blanshan popularized in PixelMath — the
formulas implemented here are ours; what is reused is the principle.

| Method | What it does | Starless image required |
|---|---|---|
| `transfer` | Attenuates the star layer without deforming it. The gentlest. | yes |
| `halo` | **Erodes** the star layer: stars shrink rather than fade. | yes |
| `morphological` | Minimum filter on the image, blended with the original. | no |

## The screen model, and why not a subtraction

The first two methods extract the star layer through the **screen model**:

$$ I = 1 - (1 - L)(1 - S) \quad\Longrightarrow\quad S = 1 - \frac{1 - I}{1 - L} $$

where $I$ is the image, $L$ the starless image and $S$ the star layer. After modifying $S$, we
recompose with the same formula.

Why not $S = I - L$? Because two light sources overlapping do not add linearly once the image is
normalized: a subtraction leaves **black holes** at the core of bright stars, where the image
saturates. The screen model naturally bounds the result and digs nothing.

## Getting the starless image

That is [StarRemoval](retina-doc://StarRemoval)'s job: apply it, keep the result in a window,
and give its identifier to `starless`. Geometry must match — the process refuses rather than
silently cropping.

If you have no starless image at hand, `morphological` works right away. It is less precise: a
minimum filter bites into every fine structure, not just stars.

## Parameters

- **`method`** — *enum* `transfer` | `halo` | `morphological`, default `transfer`.
- **`starless`** — *str*. Identifier of the starless view (`transfer` and `halo`).
- **`strength`** — *real*, default `0.5`, range `0`–`1`. Doses the effect. At `0` the image is
  returned as is.
- **`iterations`** — *int*, default `1`, range `1`–`10`. Number of erosions (`halo` and
  `morphological`). Two passes shrink markedly more than one.

## Tips & pitfalls

> **Reduce after stretching, not before.** On linear data stars occupy a few pixels and the
> reduction does not show; it is stretching that bloats them.

- `transfer` at high `strength` fades stars without shrinking them — the image can take on a
  "dirty" look if the background is noisy. Alternate with `halo`.
- An imperfect starless image (star residuals) carries into the extracted layer: the reduction
  will be partial, not wrong.
- The `morphological` method shifts fine structures by half a pixel on each pass. Over two
  iterations that starts to show on a galaxy.

## See also

- [StarRemoval](retina-doc://StarRemoval) — produce the starless image.
- [StarMask](retina-doc://StarMask) — a mask, if you would rather act yourself.
- [MorphologicalTransformation](retina-doc://MorphologicalTransformation) — bare erosion,
  without recomposition.

## References

- Bill Blanshan — PixelMath star reduction methods (principle reused here).
