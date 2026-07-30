---
id: PhaseCorrelationAlignment
category: ImageRegistration
title: Phase Correlation Alignment
brief: Starless sub-pixel registration by phase correlation in the Fourier domain (skimage + scipy).
keywords: [phase correlation, registration, sub-pixel, FFT, planetary, lucky imaging, translation]
related: [StarAlignment, FeatureAlignment, CometAlignment, DynamicAlignment]
icon: target
references:
  - "Guizar-Sicairos, M., Thurman, S. T., & Fienup, J. R. (2008). Efficient subpixel image registration algorithms. Optics Letters, 33(2), 156–158."
  - "scikit-image — skimage.registration.phase_cross_correlation documentation."
---

## Summary

`PhaseCorrelationAlignment` estimates the **global translation** between the active view and a
reference through phase correlation in the Fourier domain
(`skimage.registration.phase_cross_correlation`), at an adjustable sub-pixel precision, then
shifts every channel accordingly (`scipy.ndimage.shift`). Unlike `StarAlignment`, which matches
triangles of stars (astroalign), this process detects no landmarks at all: it compares the
luminance of the two images directly, which makes it suitable for fields **without sharp
point-like stars** (planetary, lucky imaging) or too star-poor for classic astrometric
registration.

## Use cases

- Registering a series of images or video frames of planets (Jupiter, Saturn, the Moon) in lucky
  imaging, where no point stars are available for matching.
- Aligning frames dominated by an extended object (a close-up comet, a terrestrial landscape)
  with no star catalogue involved.
- Correcting purely translational mount drift between consecutive frames, with a fast FFT-based
  computation.
- Serving as a fast, coarse registration pass ahead of a finer `StarAlignment` refinement on a
  mixed field.

## How it works

1. **Reference resolution**: `reference_path` takes priority; otherwise the open view identified
   by `reference_id` is used (`_resolve_reference`).
2. **Luminance reduction**: both the reference and the active view are converted to grayscale by
   averaging channels (`.mean(axis=2)`).
3. **Global shift estimation** $(\delta_y,\delta_x)$ via `phase_cross_correlation`, in two steps:
   an integer-pixel peak is first located through FFT phase correlation, then refined by an
   upsampled local DFT with factor `upsample` (Guizar-Sicairos algorithm) to reach a precision of
   $1/\text{upsample}$ pixel without computing a fully upsampled FFT.
4. **Translation** of the same shift applied to every channel via `scipy.ndimage.shift` (linear
   interpolation, order 1, zero-fill outside the frame).
5. Final **clipping** of values to $[0, 1]$.

> **Note** — the model is a **pure translation**: no rotation, no scaling, no distortion
> correction. It suits mount drift or atmospheric turbulence, not field rotation or optical
> distortion.

## Mathematics

Let $I_1$ be the reference luminance and $I_2$ the luminance of the view to register, both of
size $N \times N$. Write $F_1 = \mathcal{F}\{I_1\}$ and $F_2 = \mathcal{F}\{I_2\}$ for their 2D
Fourier transforms. The **normalized cross-power spectrum** is:

$$ R(u,v) = \frac{F_1(u,v)\,\overline{F_2(u,v)}}{\left|F_1(u,v)\,\overline{F_2(u,v)}\right|} $$

If $I_2$ is a shifted version of $I_1$ by $(\delta_y, \delta_x)$ (up to noise), the shift theorem
gives $F_2(u,v) = F_1(u,v)\, e^{-2\pi i (u\delta_x + v\delta_y)/N}$, so $R$ reduces to a pure
phase term, and its inverse Fourier transform

$$ r(x,y) = \mathcal{F}^{-1}\{R\}(x,y) $$

exhibits a near-Dirac peak located at $(\delta_y, \delta_x)$. The position of the maximum of
$|r|$ first gives the **integer-pixel shift**.

For sub-pixel accuracy (the `upsample` parameter), the algorithm does not re-interpolate $I_1$
and $I_2$; instead it recomputes $r$ on a grid upsampled by a factor $k = \text{upsample}$,
restricted to a small neighborhood around the integer peak, via a **matrix-multiply DFT**
(Guizar-Sicairos et al., 2008):

$$ r_k(x,y) = \sum_{u,v} R(u,v)\, e^{\,2\pi i \left(\frac{ux}{kN} + \frac{vy}{kN}\right)} $$

evaluated at only a handful of points around the integer peak — cost $O(N^2 \log N + k^2)$
instead of $O(k^2 N^2 \log(kN))$ for a fully upsampled FFT. The position of the new maximum,
divided by $k$, gives the shift $(\delta_y, \delta_x)$ to within $1/k$ pixel.

## Parameters

- **`reference_id`** — *str*, default `""`. Id of another open view to use as the registration
  reference; ignored when `reference_path` is set.
- **`reference_path`** — *path*, default `""`. Path to an image file to load as the reference,
  **taking priority** over `reference_id`.
- **`upsample`** — *int*, default `10`, range `1`–`100`. Upsampling factor of the local DFT: the
  registration precision is $1/\text{upsample}$ pixel. `upsample = 1` gives integer-pixel
  registration only (fastest); raising it (20–50) improves sub-pixel accuracy at the cost of a
  slightly heavier computation around the peak.

## Tips & pitfalls

> **Warning** — any field rotation, scale change, or residual distortion between the two images
> is **not corrected** by this process and can broaden the correlation peak, degrading the
> reliability of the estimate.

> **Note** — `reference_path` and `reference_id` do not usefully combine: the file always takes
> priority. If neither is set, the process raises an error.

- Works best on fields with strong high-frequency content (fine detail, a sharp planetary disk
  edge); a very blurred or saturated image flattens the correlation peak and degrades the
  estimate.
- On deep-sky fields poor in structure but rich in point stars, `StarAlignment` remains generally
  more robust, and natively handles rotation and scale.
- A very high `upsample` (close to 100) only pays off if the signal-to-noise ratio supports it;
  past a certain point, precision is limited by noise, not by `upsample`.

## See also

- [StarAlignment](retina-doc://StarAlignment) — star-based registration by matching star
  triangles (astroalign), handles rotation and scale.
- [FeatureAlignment](retina-doc://FeatureAlignment) — registration by ORB keypoints and a
  homography, no star catalogue required.
- [CometAlignment](retina-doc://CometAlignment) — registration on a moving cometary nucleus.
- [DynamicAlignment](retina-doc://DynamicAlignment) — manual registration via control points.

## References

- Guizar-Sicairos, M., Thurman, S. T., & Fienup, J. R. (2008). *Efficient subpixel image
  registration algorithms*. Optics Letters, 33(2), 156–158.
- scikit-image — *skimage.registration.phase_cross_correlation* documentation.
