---
id: SatelliteTrailDetection
category: MaskGeneration
title: Satellite Trail Detection
brief: Detects a linear trail (satellite/aircraft) via the Radon transform and produces a mask of the line.
keywords: [satellite, aircraft, trail, Radon transform, backprojection, mask, line detection]
related: [StarMask, RangeSelection, CosmicClip, Inpaint]
icon: line
references:
  - "Radon, J. (1917) — Über die Bestimmung von Funktionen durch ihre Integralwerte längs gewisser Mannigfaltigkeiten."
  - "scikit-image — skimage.transform.radon / iradon (Radon transform and inverse)."
---

## Summary

`SatelliteTrailDetection` automatically locates the **linear trail** left by a satellite or
aircraft on an exposure (a thin, roughly straight segment crossing all or part of the
field) and produces a binary **mask** in a new window. Detection relies on the **Radon
transform**: any straight line in the image forms a single, sharp peak there, which makes
the detection robust even for a low-contrast trail buried in sky background and stars. It is
a mask-generation process (like `StarMask` or `RangeSelection`): non-destructive, it never
modifies the source view and is itself not maskable.

![Source image — SatelliteTrailDetection](figures/source.webp)
![Generated mask — SatelliteTrailDetection](figures/mask.webp)

*A frame crossed by a trail, and the mask the process returns. The trail is injected.*

## Use cases

- **Automatically locate** a Starlink satellite or aircraft trail on a single exposure,
  without having to point it out manually.
- **Generate a mask** to subsequently remove the trail with `Inpaint` (background
  reconstruction under the mask) without affecting the rest of the image.
- **Diagnose a suspect frame** before integration: if `.angle_deg` reveals a clean straight
  line, the frame is likely contaminated and can be excluded or cleaned before
  `Integration`.
- A targeted alternative to `CosmicClip`/sigma-rejection integration when the intruder is a
  continuous segment rather than a point-like cosmic-ray hit.

## How it works

1. **High-frequency isolation**: luminance is compared against its median-filtered version
   (5×5 window), and only the positive residual is kept
   (`clip(lum − local_median, 0, ∞)`). This suppresses the sky background and smooth
   structures (nebulosity, gradients) while preserving thin, high-contrast edges — including
   the trail, which is precisely a narrow feature locally brighter than its surroundings.
2. **Radon transform** of that residual over 180 angles evenly spaced across
   `[0°, 180°)`. A line in the image produces a **single peak** in the sinogram at
   `(rho, theta)`, the sharper the longer, thinner and higher-contrast the trail is.
3. **Peak localization**: the index `(r0, t0)` of the sinogram's maximum gives the detected
   angle, stored in the instance's `angle_deg` attribute after execution.
4. **Unfiltered backprojection** of a sinogram containing only that isolated peak (everything
   else zeroed). By point-line duality, backprojecting a single sinogram point retraces
   exactly the corresponding line in the image plane — this is the key mechanism of the
   algorithm.
5. **Cropping** of the reconstruction (sized to the image diagonal by `radon`) back to the
   original `(h, w)` shape, then **thresholding** relative to the reconstructed maximum
   (`threshold`) to obtain a binary mask of the line.
6. **Thickening** of the mask via binary dilation over `width` iterations, to cover the
   trail's real width (which is never perfectly one pixel thin).

## Mathematics

The **Radon transform** of an image $f(x,y)$ integrates values along every straight line of
the plane, parameterized by its distance from the origin $\rho$ and normal orientation
$\theta$:

$$ R_\theta(\rho) = \int\!\!\int f(x,y)\,
   \delta\big(\rho - x\cos\theta - y\sin\theta\big)\, dx\, dy . $$

A **straight line** in $f$ (sharp edge, trail) concentrates its energy on a single pair
$(\rho_0, \theta_0)$: it appears in the sinogram $R_\theta(\rho)$ as a **localized peak**,
found here as $(r_0, t_0) = \arg\max R_\theta(\rho)$.

**Unfiltered backprojection** (used without the ramp filter, `filter_name=None`)
reconstructs the image space by integrating the sinogram over all angles:

$$ b(x, y) = \int_0^{\pi} p\big(x\cos\theta + y\sin\theta,\ \theta\big)\, d\theta . $$

When $p$ is zero everywhere except at the isolated point $(\rho_0, \theta_0)$, this integral
only contributes for pixels $(x, y)$ that exactly satisfy the line's normal-form equation:

$$ x\cos\theta_0 + y\sin\theta_0 = \rho_0 , $$

and $b(x,y)$ is zero elsewhere. This is the **point-line duality** of the Radon transform:
backprojecting a single sinogram point redraws, in the image plane, exactly the line it came
from. The final mask is obtained by thresholding relative to the reconstructed peak
$b_{\max}$:

$$ M(x,y) = \mathbb{1}\big[\, b(x,y) \ge \texttt{threshold} \cdot b_{\max} \,\big], $$

followed by morphological dilation over `width` iterations to give the ideally thin line a
thickness representative of the actual trail.

## Parameters

- **`threshold`** — *real*, default `0.5`, range `0.05`–`0.99`. Fraction of the
  backprojection peak above which a pixel belongs to the line mask. A low value widens the
  mask along the reconstruction (more permissive), a high value tightens it around the
  immediate neighborhood of the peak.
- **`width`** — *int*, default `2`, range `0`–`30`. Number of binary-dilation iterations
  applied to the thresholded line mask, to approximate the trail's real thickness (in
  pixels). `0` disables dilation.

## Tips & pitfalls

> **Warning** — the algorithm assumes **a single dominant trail** per image: if there are
> several, only the sinogram's strongest peak is detected, the others are ignored. Re-run the
> process after masking/handling the first trail to find another.

> **Note** — the high-pass step reacts to *any* thin, straight-line contrast: a residual
> vignetting edge, a straight-line sensor artifact, or a bright star's diffraction spike can,
> in rare cases, dominate the sinogram instead of a real trail. Visually check the produced
> mask before using it for inpainting.

- The result is a **new window** (single-channel mask): the process never modifies the
  source view, consistent with the other mask generators (`StarMask`, `RangeSelection`).
- The detected angle (`angle_deg`, in degrees, `radon`'s convention) is available on the
  process instance after execution — useful for logging or automatically flagging
  contaminated frames before integration.
- On a field with few bright stars and no strong gradient, the high-pass filter isolates the
  trail very cleanly; on a field rich in diffraction spikes, a prior `RangeSelection` or star
  mask can help clean up the input.

## See also

- [StarMask](retina-doc://StarMask) — star mask, same mask-generation family.
- [RangeSelection](retina-doc://RangeSelection) — intensity-range mask, a simpler alternative.
- [CosmicClip](retina-doc://CosmicClip) — cosmic-ray hit rejection (point-like intruders).
- [Inpaint](retina-doc://Inpaint) — background reconstruction under a mask, to erase the detected trail.

## References

- Radon, J. (1917) — *Über die Bestimmung von Funktionen durch ihre Integralwerte längs
  gewisser Mannigfaltigkeiten*.
- scikit-image — *skimage.transform.radon / iradon* (Radon transform and inverse).
