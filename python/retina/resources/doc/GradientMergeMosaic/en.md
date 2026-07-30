---
id: GradientMergeMosaic
category: BackgroundModelization
title: Mosaic Merge by Background Equalization
brief: Merges the current view with a neighboring panel, equalizing background levels and blending the overlap.
keywords: [mosaic, panels, merge, sky background, overlap, wide field]
related: [MosaicReproject, StarAlignment, PlateSolve, GradientCorrection]
icon: grid-4x4
references:
  - "PixInsight — Mosaic by CFosterMosaic / GradientMergeMosaic scripts."
  - "PixelMath-based panel blending techniques for wide-field mosaics."
---

## Summary

`GradientMergeMosaic` assembles two **panels** of a wide-field mosaic that are already
projected onto the same pixel grid (same WCS, same resolution) into one continuous image. It
**equalizes the background level** of both panels over their overlap area, then composites the
result: overlap averaged, exclusive zones copied straight from whichever panel covers them. This
is the final step of a mosaic workflow, after astrometric registration (`PlateSolve`,
`StarAlignment`) and common reprojection (`MosaicReproject`).

## Use cases

- **Assemble a wide-field mosaic** from several tiles acquired and processed separately
  (extended nebulae, Milky Way fields, short-focal-length wide fields).
- **Stitch panels whose exposure or sky background differ slightly** (different nights, moon,
  a light-pollution gradient that varies from one pointing to the next).
- **Merge an N-panel mosaic incrementally**: apply the process successively, panel after panel,
  on a composite image that grows with every call.

## How it works

The process assumes the **current view** (`data`) and the view named by `other` are already
projected onto an **identical grid** (same dimensions, same celestial frame) — that is the job
of `StarAlignment`/`PlateSolve` upstream, optionally followed by `MosaicReproject` for a shared
WCS grid. The `other` panel is resolved via `context.resolve_image_full`, which retrieves the
full `(H, W, C)` pixel array of the named view from the application's namespace.

Processing happens in three steps:

1. **Detect the useful area** of each panel: a pixel is considered "filled" when the sum of its
   channels is strictly positive (`sum(axis=2) > 0`). This distinguishes real content from the
   empty (zero) borders introduced by reprojection or registration.
2. **Equalize background over the overlap**: wherever the two panels overlap, a single **median
   offset** is computed between the pixel medians of both panels over that shared area, and
   applied to the entire `other` panel. This corrects a global sky-background shift (pedestal,
   transparency, light pollution) without touching local contrast.
3. **Composite**: where only the current panel is filled, its pixels are kept; where only
   `other` is filled, its (equalized) pixels are kept; in the overlap, the **plain average** of
   both is taken. The result is finally clipped to `[0,1]`.

If `other` is empty, cannot be resolved, or has a different shape than the current view, the
process is a no-op: it returns a copy of the input image unchanged.

## Mathematics

Let $a$ be the current panel and $b$ the `other` panel, both of shape $(H, W, C)$. Define the
filled-area masks from the per-pixel channel sum:

$$ v_a(x,y) = \mathbb{1}\!\left[\sum_c a(x,y,c) > 0\right], \qquad
   v_b(x,y) = \mathbb{1}\!\left[\sum_c b(x,y,c) > 0\right] $$

and the overlap $\Omega = \{(x,y) : v_a(x,y) \wedge v_b(x,y)\}$. If $\Omega \neq \varnothing$,
the background-equalization offset is the difference of the **robust medians** of pixel values
over the overlap:

$$ \delta = \operatorname{med}_{(x,y) \in \Omega}\big[a(x,y,\cdot)\big] -
            \operatorname{med}_{(x,y) \in \Omega}\big[b(x,y,\cdot)\big] $$

applied uniformly: $b' = b + \delta$. The median is used instead of the mean to stay insensitive
to bright stars and noise residuals that may fall inside the overlap. The final per-pixel
composite is:

$$
I(x,y) =
\begin{cases}
a(x,y) & \text{if } v_a \wedge \lnot v_b \\
b'(x,y) & \text{if } v_b \wedge \lnot v_a \\
\tfrac{1}{2}\big(a(x,y) + b'(x,y)\big) & \text{if } v_a \wedge v_b \\
0 & \text{otherwise}
\end{cases}
$$

followed by clipping $I \leftarrow \operatorname{clip}(I, 0, 1)$. The plain averaging in the
overlap leaves a **visible seam** if the two panels have very different noise levels or
resolution; there is no distance-weighted feathering toward the panel edges.

## Parameters

- **`other`** — *str*, default `""`. Identifier of the view holding the **second panel** to
  merge with the current view. Must name a view that is already open and projected onto the
  same pixel grid as the active view. If empty or unresolvable, the process does nothing.

## Tips & pitfalls

> **Warning** — both panels must be **registered onto exactly the same grid** (same dimensions,
> orientation, and sampling). `GradientMergeMosaic` performs no registration of its own: run
> `StarAlignment`/`PlateSolve` first, then `MosaicReproject` for a common WCS grid if the panels
> come from different pointings.

> **Note** — the filled-area detection relies on `sum(axis=2) > 0`: a truly black pixel (all
> channels zero) inside a real-signal region will be wrongly treated as an empty border. A small
> pedestal applied beforehand (see `GradientCorrection`) avoids this false negative.

- For a mosaic with more than two panels, apply the process **iteratively**: merge two panels
  first, then merge the result with the next panel, and so on.
- If sky backgrounds still look mismatched after merging (a visible seam outside the overlap),
  equalize each panel separately with `GradientCorrection` or `BackgroundExtraction` before
  merging.
- The equalization only corrects a **constant offset**; a residual gradient that differs between
  the two panels (e.g. asymmetric light pollution) must be handled beforehand.

## See also

- [MosaicReproject](retina-doc://MosaicReproject) — common reprojection onto a shared WCS grid.
- [StarAlignment](retina-doc://StarAlignment) — prior registration of the panels to each other.
- [PlateSolve](retina-doc://PlateSolve) — astrometric solving of each panel.
- [GradientCorrection](retina-doc://GradientCorrection) — background equalization within a panel before merging.

## References

- PixInsight — community mosaic scripts (CFosterMosaic and similar approaches).
- PixelMath-based panel blending techniques for wide-field mosaics.
