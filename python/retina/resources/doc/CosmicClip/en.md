---
id: CosmicClip
category: CosmeticCorrection
title: Cosmic Ray Removal (CosmicClip)
brief: Detects and repairs cosmic rays and hot pixels using the LA Cosmic algorithm (astroscrappy).
keywords: [cosmic ray, LA Cosmic, astroscrappy, hot pixel, laplacian, cosmetic]
related: [CosmeticCorrection, DefectMap, NoiseReduction, ImageCalibration]
icon: bolt
references:
  - "van Dokkum, P. G. (2001) — Cosmic-Ray Rejection by Laplacian Edge Detection, PASP 113, 1420."
  - "McCully, C. et al. — astroscrappy (Python implementation of L.A.Cosmic)."
---

## Summary

`CosmicClip` removes **cosmic rays** and isolated hot pixels from an image using
**astroscrappy**, the Python implementation of the **L.A.Cosmic** algorithm (Laplacian Cosmic
Ray Identification, van Dokkum 2001). Unlike a plain statistical filter on pixel value,
L.A.Cosmic exploits the **shape** of the defect: a cosmic-ray hit has a much sharper profile
(near point-like, sub-seeing scale) than the core of a real star, which lets it be detected and
repaired without eroding astronomical sources.

![Before — CosmicClip](figures/before.webp)
![After — CosmicClip](figures/after.webp)

*Cosmic-ray hits, and the frame after they are detected and replaced. The hits are injected: they are the short, bright, sharp-edged streaks that distinguish a cosmic ray from a star, and what the detector keys on.*

## Use cases

- **Clean a single sub-frame** before integration, especially for long exposures where cosmic
  rays leave bright streaks or point-like spikes.
- **Complement `Integration`**: cross-frame sigma rejection already removes most hits on a
  stack, but `CosmicClip` remains useful on isolated frames or as a pre-processing step.
- **Handle residual hot pixels** that dark calibration did not fully cancel out (sensor thermal
  drift between the dark's acquisition and the light's).

## How it works

The algorithm runs per channel (the internal image is `(H, W, C)` float32 in `[0,1]`):

1. **Rescaling**: since our data is normalized to `[0,1]`, it is temporarily converted back to
   pseudo-ADU 16-bit scale (factor `65535`) before calling `astroscrappy`, because its noise
   model (`gain`, `readnoise`) is calibrated for **real ADU** values. The cleaned result is
   divided by the same factor afterwards.
2. **Subsampled Laplacian detection**: the image is upsampled by a factor of 2 and convolved
   with a Laplacian kernel, which strongly amplifies sharp transitions (cosmic rays) while
   staying moderate on the softer profile of a star (limited by the PSF/seeing).
3. **Noise-model normalization**: the Laplacian response is divided by an expected-noise map
   derived from the Poisson+read-noise model (`gain`, `readnoise`), giving a local
   signal-to-noise ratio compared against the `sigclip` threshold.
4. **Shape filter (`objlim`)**: a second test compares the peak amplitude against a fine
   structure estimate (subtractive local median), which rejects true stellar peaks that are too
   "broad" to be a cosmic ray — this is the star-erosion safeguard.
5. **Iteration** (`iterations`): detection is repeated over pixels not yet flagged as cosmic,
   since a large hit may only reveal its center on the first pass.
6. **Repair**: each pixel flagged as a cosmic ray is replaced (interpolated from healthy
   neighbors), then the image is converted back to `[0,1]` and clipped for safety.

## Mathematics

Let $I$ be the image in pseudo-ADU. The algorithm builds the upsampled image $I_2$ (factor 2 in
both dimensions) and applies the discrete Laplacian kernel

$$ L = \begin{pmatrix} 0 & -1 & 0 \\ -1 & 4 & -1 \\ 0 & -1 & 0 \end{pmatrix}, \qquad
   L_2 = L * I_2, $$

then downsamples $L_2$ back to the original scale, keeping only its positive part
$L_2^{+} = \max(L_2, 0)$ (cosmic rays produce a local excess, never a deficit).

The expected per-pixel noise combines photon noise (Poisson on the smoothed signal $\hat I$)
and read noise $\sigma_\text{RN}$ = `readnoise`:

$$ \sigma(x,y) = \sqrt{\frac{\hat I(x,y)}{g} + \sigma_\text{RN}^2}, \qquad g = \texttt{gain} = 1, $$

where `gain` is fixed to `1.0` in this integration (our data being already normalized, no
separate sensor gain is applied). A pixel is a **cosmic-ray candidate** if its Laplacian-to-noise
ratio exceeds the clip threshold:

$$ \frac{L_2^{+}(x,y)}{\sigma(x,y)} > \texttt{sigclip}. $$

To discard star cores (broad structure, not an isolated spike), the response is also compared to
a fine-structure image $F$ (obtained from a subtractive local median) through the second
criterion:

$$ \frac{L_2^{+}(x,y)}{F(x,y)} > \texttt{objlim}, $$

only pixels satisfying **both** conditions being flagged and repaired. The process is repeated
`iterations` times to capture multi-pixel hits.

## Parameters

- **`sigclip`** — *real*, default `4.5`, range `0.5`–`20.0`. Detection threshold in units of
  Laplacian signal-to-noise ratio. Lower = more aggressive detection (risk of false positives on
  background noise); higher = more conservative (faint hits go undetected).
- **`objlim`** — *real*, default `5.0`, range `0.5`–`20.0`. Threshold of the shape criterion that
  protects real astronomical sources. Lower = protects fine stars less well (risk of eroding
  their core); higher = protects more but may let hits near stars slip through.
- **`iterations`** — *int*, default `4`, range `1`–`20`. Number of detection/repair passes.
  Useful for cosmic-ray hits spanning several contiguous pixels; beyond 4–5 passes the gain is
  usually marginal.
- **`readnoise`** — *real*, default `6.5`, range `0.0`–`100.0`. Sensor read noise, in electrons,
  used by the noise model. Fill in from the camera's datasheet (or bias-frame statistics) for
  reliable thresholding.

## Tips & pitfalls

> **Warning** — the internal scale factor (`65535`) assumes a **linear**, calibrated `[0,1]`
> image. Applying `CosmicClip` to an already-stretched image (baked STF, curves) breaks the
> Poisson noise model and degrades detection.

> **Note** — a wrong `readnoise` (too low) makes thresholding too permissive on dark areas and
> can erase real faint background pixels; too high a `readnoise` lets subtle cosmic rays through.

- On short or low-noise exposures, it can be cheaper to let `Integration`'s sigma rejection do
  the work across the stack rather than processing every sub-frame.
- On isolated lights (a single master, no stack available), `CosmicClip` is the only recourse
  since cross-frame rejection is not possible.
- Combine with `CosmeticCorrection`: it targets fixed sensor defects (systematic hot/cold
  pixels), while `CosmicClip` targets random per-exposure events.

## See also

- [CosmeticCorrection](retina-doc://CosmeticCorrection) — fixed sensor defect correction.
- [DefectMap](retina-doc://DefectMap) — explicitly applied defect map.
- [NoiseReduction](retina-doc://NoiseReduction) — general denoising, complementary.
- [ImageCalibration](retina-doc://ImageCalibration) — upstream bias/dark/flat calibration.

## References

- van Dokkum, P. G. (2001) — *Cosmic-Ray Rejection by Laplacian Edge Detection*, PASP 113, 1420.
- McCully, C. et al. — *astroscrappy* (Python implementation of L.A.Cosmic).
