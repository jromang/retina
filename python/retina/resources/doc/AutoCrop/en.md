---
id: AutoCrop
category: Geometry
title: Automatic cropping
brief: Removes the incompletely covered borders of an integrated image, from the real coverage of the frames.
keywords: [crop, autocrop, borders, coverage, dithering, integration, stacking]
related: [Crop, DynamicCrop, Integration, StarAlignment]
icon: crop
references:
  - "PixInsight — WeightedBatchPreprocessing, AutoCrop step (enabled by default)."
  - "Fruchter & Hook (2002) — coverage and weights in dithered image reconstruction."
---

## Summary

`AutoCrop` removes the border of an integrated image that was **not seen by every frame**.
After registration the frames do not overlap exactly — that is the whole point of dithering,
which deliberately offsets the pointing between exposures. The common area is therefore
smaller than the sensor, and anything beyond it received only some of the frames, when it
received any at all.

Unlike [Crop](retina-doc://Crop), which applies bounds you give it, `AutoCrop` **finds** them.

![Before — AutoCrop](figures/before.webp)
![After — AutoCrop](figures/after.webp)

*A rotated frame with the black margins the rotation leaves, and the same frame after they are trimmed off. The margins are not staged: removing them is the step that normally follows a rotation.*

## Use cases

- **After an integration**, as the last step: this is the default in the automated
  preprocessing pipeline (`retina.pipeline`), and in WBPP.
- **Before an automatic stretch**: a poorly covered border skews the median and MAD from
  which the STF derives its thresholds, and the whole image ends up badly stretched.
- **Before any noise or background measurement**, for the same reason.
- **Before export**, so as not to ship an image framed by a ragged dark edge.

## How it works

Coverage is measured on the **registered frames**, passed in `frames`, not on the integrated
image. This is the crucial point: in the integrated image a border seen by half the frames is
not zero, merely attenuated. It would therefore go unnoticed — yet it is exactly the case we
want to remove, since its signal-to-noise ratio is half that of the centre with nothing to
say so.

Each registered frame contributes an "observed pixel" mask (non-zero value: this is why
`StarAlignment` fills out-of-field areas with zero rather than a plausible value). The sum of
those masks, divided by the number of frames, gives the coverage map.

Cropping is then **iterative**, and it has to be: a single empty column drops the coverage of
*every* row below the threshold. Evaluating rows and columns once and for all over the whole
image would therefore crop far beyond what is needed. On each pass the least covered edge is
removed, coverage is recomputed on the remaining rectangle, and the process stops as soon as
all four edges reach `coverage`.

Without a `frames` list we fall back on the only test available from a single image — exactly
zero pixels — which detects only borders seen by *no* frame at all.

## Mathematics

Given $N$ registered frames $F_k$ of size $H \times W$, the observation mask of frame $k$ is

$$ m_k(y,x) = \begin{cases} 1 & \text{if } \max_c |F_k(y,x,c)| > 0 \\ 0 & \text{otherwise} \end{cases} $$

and the coverage map is their mean:

$$ C(y,x) = \frac{1}{N} \sum_{k=1}^{N} m_k(y,x) \in [0,1] $$

We look for a rectangle $R = [y_0, y_1) \times [x_0, x_1)$ such that each of its four edges is
fully covered in a proportion of at least $\tau$ (`coverage`):

$$ \frac{1}{x_1-x_0}\sum_{x=x_0}^{x_1-1} \mathbb{1}\!\left[C(y_0,x) \ge 1\right] \ \ge\ \tau $$

and symmetrically for $y_1-1$, $x_0$ and $x_1-1$. The rectangle starts as the whole image and
shrinks by one row or column at a time, removing the least covered edge on each pass, until
the condition holds or the `max_fraction` limit is reached.

## Parameters

- **`coverage`** — *real*, default `0.98`, range `0`–`1`. Minimum fraction of **fully
  covered** pixels required on an edge for it to be kept. The default tolerates a few missing
  pixels (an isolated defect, a saturated star at the edge) without cropping.
- **`max_fraction`** — *real*, default `0.25`, range `0`–`0.9`. Largest share of each
  dimension we allow ourselves to remove. A safeguard: beyond that, the cause is more likely
  an image legitimately dark at its edges than a coverage problem.
- **`frames`** — *pathlist*, default empty. The registered frames that fed the integration.
  When empty, coverage is inferred from the image itself — far less reliable.

## Tips & pitfalls

> **Warning** — measuring coverage on the integrated image alone (without `frames`) detects
> only borders where **no** frame contributed. Partially covered borders, which are the
> common case with dithering, are invisible there: averaging attenuates them without zeroing
> them.

> **Note** — `AutoCrop` assumes unobserved areas are zero. That is the case for
> [StarAlignment](retina-doc://StarAlignment) output, whose `fill_value` parameter defaults to
> zero. A median fill, common elsewhere, would fabricate plausible sky where nothing was seen
> and make coverage undetectable.

- Apply `AutoCrop` **before** normalisation or stretching, never after: the whole point is
  that those steps should no longer see the doubtful borders.
- An unusually large crop often signals dithering that was too wide, or a reference frame
  poorly chosen at the edge of the set: the value returned by `bounds()` is a good diagnostic.

## See also

- [Crop](retina-doc://Crop) — cropping to explicit bounds.
- [DynamicCrop](retina-doc://DynamicCrop) — interactive cropping combined with a rotation.
- [StarAlignment](retina-doc://StarAlignment) — produces the registered frames and their fill.
- [Integration](retina-doc://Integration) — the stack whose result `AutoCrop` cleans up.

## References

- PixInsight — *WeightedBatchPreprocessing*, AutoCrop step (enabled by default).
- Fruchter & Hook (2002) — coverage and weights in dithered image reconstruction.
