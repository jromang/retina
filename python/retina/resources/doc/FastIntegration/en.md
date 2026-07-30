---
id: FastIntegration
category: ImageIntegration
title: Fast Integration (no rejection)
brief: Stacks multiple frames with a plain mean or median, without sigma rejection — for a quick preview.
keywords: [integration, stacking, mean, median, preview, no rejection]
related: [Integration, StarAlignment, DrizzleIntegration, ImageCalibration]
icon: stack-2
references:
  - "PixInsight — ImageIntegration tool reference (no-rejection mode)."
  - "numpy.mean / numpy.median."
---

## Summary

`FastIntegration` combines a list of frames into a single image by plain **mean** or **median**,
**without any sigma rejection**. It is the lightweight sibling of `Integration`: it trades
robustness against outliers (cosmic rays, satellites, planes) for much faster execution. It is a
**global** process: it reads a list of files from disk and creates a new window, it does not
operate on an already-open view.

## Use cases

- **Quick preview** of a stack during an acquisition session, to judge framing or noise level
  without waiting for a full sigma-rejection pass.
- **Large frame counts** (hundreds) where the per-pixel statistical rejection cost becomes
  significant and a simple SNR gain is enough.
- **Already clean frames** (few or no outliers, e.g. studio/planetary capture at high cadence)
  where sigma rejection would add nothing.
- Quick **median** combination to coarsely discard a few isolated outliers without paying the
  cost of a full robust estimate (median + mad_std).

## How it works

Each file in `frames` is loaded and converted to `float32`, then all frames are stacked into a
cube $(N, H, W, C)$ — they must therefore share the **same geometry** (already calibrated and
aligned, as for `Integration`). Depending on `combine`, the result is either the **mean** or the
**median** of the cube along the frame axis ($N$), computed directly with `numpy.mean`/
`numpy.median` — no rejection iteration, no weighting, no per-frame noise estimation. The result
is then placed in a new window named `new_image_id`.

## Mathematics

For a stack of values $\{x_i\}_{i=1}^{N}$ at a given pixel position, the result is, depending on
`combine`:

$$ \bar{x}_{\text{mean}} = \frac{1}{N}\sum_{i=1}^{N} x_i
   \qquad\text{or}\qquad
   \bar{x}_{\text{median}} = \operatorname{med}(x_i). $$

The mean minimizes squared error and improves the signal-to-noise ratio by a theoretical factor
of $\sqrt{N}$ for independent identically distributed Gaussian noise, but **no value is
discarded**: a single aberrant pixel (cosmic ray) directly contaminates the mean at that pixel.
The median is inherently more resistant — it tolerates up to $\lfloor N/2 \rfloor$ outlying
values without being affected — but is less efficient than the mean on clean noise, and lacks
the finesse of a sigma rejection adaptive to local dispersion (like `Integration`'s mad_std).

## Parameters

- **`frames`** — *pathlist*, default `[]`. List of files to stack (already calibrated and
  aligned, same geometry for all).
- **`combine`** — *enum*, default `mean`, choices: `mean`, `median`. Combination mode: plain mean
  (best SNR on clean data) or median (more resistant to isolated outliers).
- **`new_image_id`** — *str*, default `fast_integration`. Identifier of the resulting window.

## Tips & pitfalls

> **Warning** — without sigma rejection, a single cosmic ray or satellite trail on one frame
> **survives** in the result (attenuated but present with `mean`, potentially visible as-is if
> more than half the frames are contaminated at the same position with `median`). For a final
> master intended for downstream processing, prefer `Integration`.

- Frames must be **aligned** beforehand (`StarAlignment`): `FastIntegration` performs no
  registration and stacks pixel by pixel.
- Useful for **quick previewing** during acquisition; switch to `Integration` for the final
  master once the session is complete.
- `combine = median` is a good compromise when a few frames are clearly bad but you don't want
  to pay the cost of a full sigma-rejection pass.

## See also

- [Integration](retina-doc://Integration) — stacking with robust sigma rejection (median +
  mad_std), for the final master.
- [StarAlignment](retina-doc://StarAlignment) — frame registration, a mandatory prerequisite.
- [DrizzleIntegration](retina-doc://DrizzleIntegration) — drizzle integration (upsampling).
- [ImageCalibration](retina-doc://ImageCalibration) — upstream bias/dark/flat calibration.

## References

- PixInsight — *ImageIntegration* tool reference (no-rejection mode).
- numpy — *mean* / *median*.
