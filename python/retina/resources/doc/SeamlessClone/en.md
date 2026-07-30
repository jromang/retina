---
id: SeamlessClone
category: Painting
title: Seamless Clone
brief: Copies a disk of pixels from a source to a destination by blending gradients (OpenCV Poisson seamlessClone) instead of alpha, so seams disappear.
keywords: [cloning, clone stamp, Poisson, seamlessClone, retouching, gradient blending, inpainting]
related: [CloneStamp, Inpaint, StarRemoval, CosmeticCorrection]
icon: copy
references:
  - "Pérez, P., Gangnet, M., Blake, A. (2003) — Poisson Image Editing, ACM SIGGRAPH."
  - "OpenCV — cv2.seamlessClone (Photo module, NORMAL_CLONE mode)."
---

## Summary

`SeamlessClone` copies a disk of pixels sampled around a **source** point onto a
**destination** point, but instead of blending colors through a plain alpha fade like
`CloneStamp`, it recomposes the patch through **gradient blending** (OpenCV's Poisson
algorithm, `cv2.seamlessClone`). The result keeps the source patch's texture and high
frequencies while matching the destination background's average color and lighting exactly:
the seam becomes undetectable, even over a structured background (nebulosity, sky-background
gradient, residual vignetting).

## Use cases

- **Erase an extended defect** (sensor artifact, satellite trail not covered by
  `CosmeticCorrection`, optical reflection) by covering it with a patch taken elsewhere in the
  same sky background.
- **Duplicate a clean background patch** over a polluted zone (reflection halo, local gradient)
  without leaving a visible edge, unlike a plain copy-paste.
- **Repair a large region** after aggressive star removal, when `Inpaint` produces a flat area
  that is too smooth and real background texture is preferable.
- **Pre-process a zone before mosaicking/compositing** to homogenize a panel junction over a
  small overlap area.

## How it works

1. A **square patch** of side $2r+1$ is extracted around the source point
   $(src\_x, src\_y)$, where $r$ = `radius`. If this square falls outside the image, the
   operation is a **no-op** (image unchanged): the source must be fully contained.
2. A **filled circular mask** (radius $r$, centered on the patch) delimits the region to
   clone: only the disk inside the square is actually blended, avoiding an artificial square
   boundary for the solver.
3. Pixels are converted to **8-bit, 3 channels** (an OpenCV requirement); a monochrome image
   is replicated across 3 channels before the call, and the result is reduced back to 1
   channel by averaging the 3 blended channels.
4. `cv2.seamlessClone` is called in **`NORMAL_CLONE`** mode: it solves a Poisson equation that
   forces the pasted patch to reproduce the **internal gradients** of the source patch while
   forcing its **border** to match the existing destination background. The paste center must
   be at least $r$ pixels from every image edge, otherwise the call is also a no-op (the
   solver needs a full neighborhood around the disk).
5. The blended patch replaces the region around `(dst_x, dst_y)`; the rest of the image is
   unchanged.

## Mathematics

Let $\Omega$ be the disk of radius $r$ centered on the destination, $\partial\Omega$ its
boundary, $g$ the source patch (viewed as a continuous function over $\Omega$), and $f^*$ the
existing destination background. Poisson blending (Pérez, Gangnet & Blake, 2003) looks for the
function $f$ defined over $\Omega$ that **minimizes the gradient mismatch** with the source
while **matching** the background exactly at the boundary:

$$
f = \arg\min_{f} \iint_{\Omega} \big|\nabla f - \nabla g\big|^2 \, \mathrm{d}\Omega,
\qquad \text{subject to } f\big|_{\partial\Omega} = f^*\big|_{\partial\Omega}.
$$

The Euler–Lagrange equation for this variational problem is a **Poisson equation** with a
Dirichlet boundary condition:

$$
\Delta f = \Delta g \ \text{ over } \Omega, \qquad f\big|_{\partial\Omega} = f^*\big|_{\partial\Omega},
$$

where $\Delta$ is the discrete Laplacian (sum of differences with the 4 neighbors). In
`NORMAL_CLONE` mode, the guidance field is exactly $\nabla g$ (the source patch's internal
gradients are carried over in full); OpenCV solves this sparse linear system per channel. The
result $f$ therefore has the source's **local texture and contrast**, but a **mean level**
that connects continuously to the destination background — this is what makes the seam
invisible where a plain $\alpha$-blend (like `CloneStamp`) leaves a halo as soon as the two
zones' average brightness differs.

## Parameters

- **`src_x`** — *int*, default `0`, range `0`–`1,000,000`. X coordinate (pixels) of the source
  patch's center to copy.
- **`src_y`** — *int*, default `0`, range `0`–`1,000,000`. Y coordinate (pixels) of the source
  patch's center.
- **`dst_x`** — *int*, default `0`, range `0`–`1,000,000`. X coordinate (pixels) of the
  destination center where the blended patch is pasted.
- **`dst_y`** — *int*, default `0`, range `0`–`1,000,000`. Y coordinate (pixels) of the
  destination center.
- **`radius`** — *int*, default `12`, range `2`–`500`. Radius (pixels) of the cloned disk. Also
  sets the extracted square patch's side ($2r+1$) and the minimum margin required between the
  destination center and the image edges.

## Tips & pitfalls

> **Warning** — if the source or destination are too close to an edge (less than `radius`
> pixels), the process is a **silent no-op**: the image comes out unchanged with no error.
> Always check the result, especially with a large radius near corners.

> **Note** — unlike `CloneStamp`, there is no `softness` parameter: the blending is handled by
> the Poisson solve itself, not by an alpha gradient at the disk's edge.

- Pick a source whose **texture** (noise, background grain) resembles the destination's: Poisson
  blending fixes the mean brightness, not the grain.
- For small, localized touch-ups (hot pixels, isolated defects), `CloneStamp` with a small
  radius is often sufficient and cheaper; reserve `SeamlessClone` for larger areas where a
  mean-level seam must be invisible.
- Too large a radius can pull structures (stars, filaments) into the source patch, which will
  then be duplicated recognizably in the destination.

## See also

- [CloneStamp](retina-doc://CloneStamp) — simple clone stamp with alpha blending, faster.
- [Inpaint](retina-doc://Inpaint) — fills a masked region by propagating gradients, with no
  explicit source.
- [StarRemoval](retina-doc://StarRemoval) — star removal, filled in by inpainting.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — automatic correction of point defects
  (hot/dead pixels).

## References

- Pérez, P., Gangnet, M., Blake, A. (2003) — *Poisson Image Editing*, ACM SIGGRAPH.
- OpenCV — *cv2.seamlessClone* (Photo module, `NORMAL_CLONE` mode).
