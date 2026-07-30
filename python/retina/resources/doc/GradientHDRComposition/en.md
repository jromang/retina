---
id: GradientHDRComposition
category: ImageIntegration
title: Gradient-Domain HDR Composition
brief: Merges several registered exposures by keeping the strongest-magnitude gradient at each pixel, then reconstructs via Poisson solving.
keywords: [HDR, gradient domain, Poisson, gradient, dynamic range, fusion, registration]
related: [HDRComposition, GradientHDRCompression, StarAlignment, Integration]
icon: stack
references:
  - "Fattal, R., Lischinski, D., Werman, M. — Gradient Domain High Dynamic Range Compression (SIGGRAPH 2002)."
  - "PixInsight — HDRComposition tool reference."
  - "scipy.fft — dctn/idctn (discrete cosine transform)."
---

## Summary

`GradientHDRComposition` is a **global** process that combines several **registered** exposures
(same pixel grid, different exposure times) into a single high dynamic range image. Rather than
blending intensities pixel by pixel, the algorithm works in the **gradient domain**: at each
position it keeps the gradient vector of strongest magnitude among all the frames (i.e. the
best-exposed detail — the sharp core from a short exposure, or the faint extension from a long
one), then reconstructs the image by solving a Poisson equation over the merged gradient field.
The result shows no seams and no visible saturation, without the ring-shaped halos typical of
classic multiscale compositions.

## Use cases

- **Merge a series of short/long exposures** of the same object (pre-registered, e.g. via
  `StarAlignment`) to reveal both the bright core of a galaxy or globular cluster and its faint
  outer extensions at once, with no single frame dominating.
- **Compose an HDR nebula image** where short exposures protect saturated central stars while
  long exposures supply the faint signal of the outer wisps.
- Alternative to `HDRComposition` (intensity-weighted fusion) when preserving **local structural
  detail** matters more than a simple exposure-weighted average.

## How it works

For every frame and every channel:

1. The image is passed through a **logarithm** (after clipping to a floor value, to avoid
   `log(0)`), which linearizes perceived contrast across several orders of magnitude.
2. The **forward gradient** `(gx, gy)` is computed by simple finite differences (right/bottom
   border set to zero).
3. At each pixel, the **squared magnitude** of the current frame's gradient is compared against
   the best magnitude retained so far, and the winning vector is kept — the frame expressing the
   strongest local contrast at that location wins.

Once every frame has been scanned, the merged gradient field `(best_gx, best_gy)` is integrated:
its **divergence** is computed (the discrete adjoint of forward differences), then a **Poisson
equation** with Neumann boundary conditions is solved via the discrete cosine transform (DCT),
which diagonalizes the 5-point Laplacian on a regular grid. The resulting log-luminance is
exponentiated and linearly renormalized to `[0, 1]` per channel, and the new image is published
under the `new_image_id` identifier.

> **Note** — the merged gradient field is generally not an exact gradient (it need not derive
> from a single scalar potential). The Poisson solve yields its **least-squares reconstruction**,
> which is why no seams appear even where neighboring regions come from different frames.

## Mathematics

Let $I_k(x,y)$ be the $k$-th frame (out of $N$ registered exposures), and
$L_k = \log(\max(I_k, \varepsilon))$ its per-channel log-luminance. The discrete forward gradient is:

$$ \nabla L_k(x,y) = \big(L_k(x{+}1,y) - L_k(x,y),\; L_k(x,y{+}1) - L_k(x,y)\big) = (g_x^k, g_y^k). $$

At each pixel, the frame with the strongest gradient magnitude is selected:

$$ k^\star(x,y) = \arg\max_k \; \big(g_x^k(x,y)\big)^2 + \big(g_y^k(x,y)\big)^2, \qquad
   (G_x, G_y) = \big(g_x^{k^\star}, g_y^{k^\star}\big). $$

The scalar field $L$ whose gradient best matches $(G_x, G_y)$ in the least-squares sense is then
sought, which leads to the **Poisson equation**:

$$ \nabla^2 L = \operatorname{div}(G_x, G_y), $$

with **Neumann** boundary conditions (zero flux at the edges). Discretized on a regular grid,
this equation is diagonalized in the cosine basis (DCT-II): the 5-point Laplacian becomes
multiplicative per frequency,

$$ \lambda(u,v) = 2\cos\!\Big(\frac{\pi u}{H}\Big) - 2 + 2\cos\!\Big(\frac{\pi v}{W}\Big) - 2, $$

and the solution is obtained as $L = \operatorname{DCT}^{-1}\!\big(\operatorname{DCT}(\operatorname{div}
(G_x,G_y)) / \lambda\big)$, with the constant mode ($u=v=0$, undefined since $\lambda(0,0)=0$)
fixed to zero, since only a global offset of $L$ is left undetermined. The final image is
$I' = \exp(L)$, linearly renormalized per channel to $[0,1]$.

## Parameters

- **`frames`** — *pathlist*, default `[]`. List of file paths of the **registered** exposures
  (same pixel grid) to combine. At least one frame is required; an empty list raises an error.
- **`new_image_id`** — *str*, default `gradient_hdr`. Identifier of the window created to hold
  the fusion result.

## Tips & pitfalls

> **Warning** — the frames must be **precisely registered** before calling this process (same
> resolution, same orientation, aligned pixels). Any misalignment, even sub-pixel, produces
> gradient artifacts (doubled edges, fringes) in the reconstruction.

- The result depends heavily on the **relative contrast** of the input frames: overly noisy
  frames can locally "win" the gradient selection and inject noise into the reconstruction. A
  light denoise pass beforehand (`NonLocalMeansDenoise`, `WaveletDenoise`) on the weaker frames
  reduces this risk.
- The final per-channel renormalization to `[0, 1]` can slightly decorrelate the gain between
  color channels; check white balance after fusion (`ColorCalibration` or
  `BackgroundNeutralization`).
- For a simple exposure-weighted intensity fusion without the gradient domain (faster, less
  refined on local detail), see `HDRComposition`.
- The same Poisson/DCT engine powers `GradientHDRCompression`, which compresses the dynamic
  range of a **single image** instead of merging several frames.

## See also

- [HDRComposition](retina-doc://HDRComposition) — intensity-weighted HDR fusion (no gradient domain).
- [GradientHDRCompression](retina-doc://GradientHDRCompression) — gradient-domain dynamic range compression on a single image.
- [StarAlignment](retina-doc://StarAlignment) — prior frame registration (a prerequisite).
- [Integration](retina-doc://Integration) — classic stacking with sigma rejection (SNR, not HDR).

## References

- Fattal, R., Lischinski, D., Werman, M. — *Gradient Domain High Dynamic Range Compression* (SIGGRAPH 2002).
- PixInsight — *HDRComposition* tool reference.
- scipy.fft — *dctn*/*idctn* (discrete cosine transform).
