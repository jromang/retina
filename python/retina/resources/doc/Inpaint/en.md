---
id: Inpaint
category: Painting
title: Inpaint Fill
brief: "Fills a defect map or the holes left by star removal by propagating the surrounding gradients (OpenCV Telea/Navier-Stokes)."
keywords: [inpainting, star removal, defects, Telea, Navier-Stokes, fill, mask]
related: [StarRemoval, DefectMap, CloneStamp, SeamlessClone]
icon: eraser
references:
  - "Telea, A. — An Image Inpainting Technique Based on the Fast Marching Method, 2004."
  - "Bertalmio, M., Bertozzi, A., Sapiro, G. — Navier-Stokes, Fluid Dynamics, and Image and Video Inpainting, 2001."
  - "OpenCV — cv::inpaint (photo module)."
---

## Summary

`Inpaint` reconstructs a designated region of the image by **propagating information from the
surrounding healthy pixels** inward, rather than simply averaging local values. It relies on
OpenCV's two inpainting algorithms — **Telea** (fast-marching guided by isophotes) and
**Navier-Stokes** (fluid-dynamics-inspired diffusion) — both noticeably more natural than a
median filter or a plain interpolation fill, especially over structured backgrounds
(nebulosity, sky-background gradients).

## Use cases

- **Fill the holes left by `StarRemoval`**: removed stars leave dark or empty disks that
  `Inpaint` closes by continuing the surrounding background structures.
- **Erase point-like artifacts**: residual hot pixels, a short satellite trail, sensor dust,
  driven from a **defect map** (see `DefectMap`).
- **Repair a damaged area** after compositing or a partial mosaic, as a scriptable alternative
  to the manual `CloneStamp`/`SeamlessClone` gesture.
- **Preprocess before analysis** (source detection, PSF measurement) so a point defect does not
  pollute local statistics.

## How it works

The process first determines a **binary mask** of the pixels to reconstruct:

1. If `mask_path` points to a file, it is loaded (red channel if color) and every **non-zero**
   pixel marks an area to fill.
2. Otherwise the mask is derived directly from the image: the **luminance** (mean of the
   channels, or the single channel for grayscale) is compared to `zero_threshold` — any pixel
   at or below the threshold is treated as a "hole" (the typical case for star removal, whose
   disks are zeroed out upstream).

If no pixel is selected, the image is returned unchanged. Otherwise each channel is converted
to 8 bits and passed to `cv2.inpaint`, which reconstructs the masked area by propagating from
its boundary, with a neighborhood `radius` and a chosen method (`telea` or `ns`) — the result
is converted back to float32 `[0,1]`.

## Mathematics

**Telea method (Fast Marching Method).** Pixels on the boundary of the hole are processed
first, then the front advances inward following the increasing order of an arrival-time map $T$
computed by fast marching (FMM). For a pixel $p$ to be reconstructed, the value is a weighted
average of the known pixels $q$ in its neighborhood of radius `radius`:

$$
I(p) = \frac{\displaystyle\sum_{q \,\in\, B_r(p)\,\cap\,\text{known}} w(p,q)\,
\big[\,I(q) + \nabla I(q)\cdot(p-q)\,\big]}
{\displaystyle\sum_{q \,\in\, B_r(p)\,\cap\,\text{known}} w(p,q)}
$$

where the weight combines three factors — direction, distance, and arrival level:

$$
w(p,q) = \operatorname{dir}(p,q)\cdot\operatorname{dst}(p,q)\cdot\operatorname{lev}(p,q),
\qquad
\operatorname{dir}(p,q) = \frac{(p-q)\cdot N(p)}{\lVert p-q\rVert},\quad
\operatorname{dst}(p,q) = \frac{1}{\lVert p-q\rVert^{2}},\quad
\operatorname{lev}(p,q) = \frac{1}{1+\lvert T(p)-T(q)\rvert}.
$$

The term $\nabla I(q)\cdot(p-q)$ locally extends the **isophote** (equal-intensity line) from
$q$ toward $p$, producing a reconstruction that follows existing gradients rather than a flat fill.

**Navier-Stokes method.** The hole is filled by iteratively solving a transport equation that
treats the image Laplacian $\omega = \Delta I$ as a **vorticity** in the fluid-dynamics sense,
transported along the isophotes:

$$ \frac{\partial I}{\partial t} = \nabla^{\perp}\omega \cdot \nabla I, $$

alternated with **anisotropic diffusion** steps that smooth the result while respecting edges,
until convergence over the masked area. This approach is generally smoother but somewhat more
costly than Telea on large areas.

## Parameters

- **`mask_path`** — *path*, default `""`. Path to an image used as a mask map; any non-zero
  pixel (red channel if color) marks an area to fill. Empty = mask derived from
  `zero_threshold`.
- **`zero_threshold`** — *real*, default `0.0`, range `0`–`1`. Luminance threshold at or below
  which a pixel is treated as a hole, used only when `mask_path` is empty (typical case: holes
  left at zero by star removal).
- **`radius`** — *int*, default `3`, range `1`–`30`. Radius (in pixels) of the neighborhood of
  known pixels considered when reconstructing each hole pixel.
- **`method`** — *enum*, default `telea`, choices `telea` / `ns`. Inpainting algorithm: Telea
  (fast marching, fast and crisp) or Navier-Stokes (fluid diffusion, smoother).

## Tips & pitfalls

> **Warning** — over **large areas** to fill, inpainting invents a plausible but **not real**
> texture: it never "rediscovers" lost astronomical signal. Reserve it for small defects
> (point-like stars, artifacts) and document its use if the image is published.

> **Note** — processing is done independently per channel; on a color image with a strong local
> RGB imbalance (chromatic halo around a removed star), a faint hue artifact can remain at the
> center of the filled disk.

- Too large a `radius` over-smooths and can make the structured background "bleed" into the
  hole; start small (2–4) and only increase if residual fringes remain.
- To fill hundreds of removed stars at once, prefer a single mask cumulating all the disks
  rather than calling the process pixel by pixel.
- `ns` often gives a smoother result over extended nebulosity; `telea` is more faithful on
  sharp edges (mosaic seams, rectangular artifacts).

## See also

- [StarRemoval](retina-doc://StarRemoval) — removes stars and typically supplies the holes to fill.
- [DefectMap](retina-doc://DefectMap) — builds a defect map reusable as `mask_path`.
- [CloneStamp](retina-doc://CloneStamp) — manual disk-copy retouching, a directed alternative.
- [SeamlessClone](retina-doc://SeamlessClone) — Poisson-blended cloning for large areas.

## References

- Telea, A. — *An Image Inpainting Technique Based on the Fast Marching Method*, 2004.
- Bertalmio, M., Bertozzi, A., Sapiro, G. — *Navier-Stokes, Fluid Dynamics, and Image and Video Inpainting*, 2001.
- OpenCV — *cv::inpaint* (photo module).
