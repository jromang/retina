---
id: CosmeticCorrection
category: CosmeticCorrection
title: Cosmetic Correction
brief: "Corrects hot/cold pixels by deviation from the local median (auto CC style)."
keywords: [hot pixels, cold pixels, sensor defects, local median, MAD, cosmetic]
related: [DefectMap, CosmicClip, Superbias, NoiseReduction]
icon: bandage
references:
  - "PixInsight — CosmeticCorrection tool reference (Auto Detect)."
  - "scipy.ndimage.median_filter — local median filter."
---

## Summary

`CosmeticCorrection` removes **static hot and cold pixels** from the sensor — photosites that
always read too high or too low, regardless of the actual signal. For each pixel, the algorithm
compares its value to the **median of its 3×3 neighborhood**; if the deviation exceeds a
threshold expressed in robust deviations (σ via MAD), the pixel is replaced by that local
median. This is the equivalent of PixInsight's CosmeticCorrection tool in "Auto Detect" mode,
without a prior defect map.

## Use cases

- **Clean a master dark/flat or a light frame** of its hot/cold pixels before integration, when
  no defect map is available.
- **Complement calibration** (`ImageCalibration`): dark subtraction does not always perfectly
  remove defective pixels whose behaviour drifts with temperature or exposure time.
- **Pre-process before `StarAlignment`/`Integration`** so isolated outlier pixels don't skew the
  rejection statistics.

## How it works

The processing runs independently on each channel:

1. A **3×3 median filter** (`scipy.ndimage.median_filter`, `reflect` mode at the borders) gives,
   for every pixel, a local estimate of the expected signal in the absence of a defect.
2. The deviation between the pixel value and this local median (`diff = ch - med`) is computed
   over the whole channel.
3. A **robust scale** of that deviation is estimated via MAD (Median Absolute Deviation), scaled
   by the factor $1.4826$ to be comparable to a Gaussian standard deviation.
4. A pixel is flagged **hot** if its deviation exceeds `hot_sigma` times that scale, **cold** if
   it falls below `-cold_sigma` times that scale.
5. Flagged pixels are **replaced by the local median**; the rest are left unchanged.

Unlike `CosmicClip` (LA Cosmic model, designed for point-like cosmic rays that occur randomly
from one exposure to the next), `CosmeticCorrection` targets **static** sensor defects — the
same defective pixels frame after frame — via a simple deviation from the local neighborhood,
without any PSF model or trail-edge detection.

## Mathematics

For a channel $I$, let $M$ be its local 3×3 median: $M(x,y) = \operatorname{med}_{(u,v) \in
\mathcal{N}_{3\times3}(x,y)} I(u,v)$. Form the residual $D = I - M$, then its robust scale over
the whole image:

$$ s = 1.4826 \cdot \operatorname{med}\big(\,|D - \operatorname{med}(D)|\,\big). $$

The factor $1.4826$ makes $s$ consistent with a standard deviation for a Gaussian distribution,
which lets the `hot_sigma`/`cold_sigma` thresholds be expressed in interpretable $\sigma$ units.
A pixel $(x,y)$ is corrected according to:

$$
I'(x,y) =
\begin{cases}
M(x,y) & \text{if } D(x,y) > h \cdot s \quad \text{(hot)} \\
M(x,y) & \text{if } D(x,y) < -c \cdot s \quad \text{(cold)} \\
I(x,y) & \text{otherwise}
\end{cases}
$$

where $h$ = `hot_sigma` and $c$ = `cold_sigma`. If $s$ is zero (a perfectly flat image), a floor
of $10^{-6}$ avoids division by zero and prevents any spurious correction.

## Parameters

- **`hot_sigma`** — *real*, default `3.0`, range `0.5`–`20.0`. Detection threshold for hot
  pixels, in robust deviations (σ) above the local median. The lower the value, the more
  aggressive the detection (risk of correcting real fine signal, such as a star core).
- **`cold_sigma`** — *real*, default `3.0`, range `0.5`–`20.0`. Detection threshold for cold
  pixels, symmetric to `hot_sigma` below the local median.

## Tips & pitfalls

> **Warning** — too low a threshold (close to 0.5) treats ordinary photon noise or fine stars
> as defects and crushes them to the local median, degrading the image's fine detail. Start
> around 3–5σ and refine visually.

> **Note** — the filter is applied channel by channel without regard for the Bayer structure,
> so run `CosmeticCorrection` **before** `Debayer` on raw CFA frames, or on the separate
> sub-images produced by `SplitCFA` if the sensor pattern must be respected.

- If the defective pixels are known and stable (a map derived from a master dark), prefer
  `DefectMap`, which is safer since it only touches the flagged positions, with no false
  positives.
- Running `CosmeticCorrection` on calibration masters, combined with `Superbias`, limits the
  propagation of defective pixels through the whole stack of calibrated frames.

## See also

- [DefectMap](retina-doc://DefectMap) — targeted correction via a supplied defect map.
- [CosmicClip](retina-doc://CosmicClip) — cosmic ray rejection (LA Cosmic model).
- [Superbias](retina-doc://Superbias) — bias modelling, another calibration step.
- [NoiseReduction](retina-doc://NoiseReduction) — general denoising, not to be confused with
  point-defect correction.

## References

- PixInsight — *CosmeticCorrection* tool reference (Auto Detect mode).
- scipy.ndimage — *median_filter*, local median filter.
