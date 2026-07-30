---
id: DefectMap
category: CosmeticCorrection
title: Defect Map
brief: Replaces pixels flagged as defective in an external map with the local median of their neighborhood.
keywords: [hot pixels, cold pixels, sensor, defective columns, local median, defect map]
related: [CosmeticCorrection, PixelInterpolation, CosmicClip, Superbias]
icon: grid-pattern
references:
  - "PixInsight — CosmeticCorrection tool reference (Defect List / Master Dark based detection)."
  - "scipy.ndimage.median_filter — sliding median filter."
---

## Summary

`DefectMap` corrects a sensor's defective pixels (hot, cold, dead columns or rows) using an
**externally supplied defect map**, rather than an automatic statistical detector. Every pixel
flagged non-zero in the map is replaced with the **local median** of its neighborhood in the
image being processed. It is the "fixed map" counterpart of `CosmeticCorrection`: useful when
defect locations are known in advance (analysis of a master dark, manufacturer mapping) and must
be applied identically across a whole series of frames, regardless of the noise or signal present
in each individual frame.

## Use cases

- **Fix recurring hot/cold pixels** of a given sensor, identified once from a master dark or bias,
  and reused across an entire session or instrument.
- **Mask a known defective column or row** (a fabrication defect) without relying on a statistical
  threshold that might miss it on some exposures.
- **Process a homogeneous batch** (same camera, same configuration) with a reproducible correction
  that is identical frame after frame, unlike a per-frame statistical detector.

## How it works

1. The **defect map** (`map_path`) is loaded through the same generic loader used for images
   (`load_image_array`, supporting FITS/XISF/TIFF/PNG/JPEG/BMP). If the loaded map is a color
   image, only its first channel is used as the mask.
2. A pixel is considered **defective** when its value in the map is **non-zero** — the map is
   therefore typically a binary image (0 = healthy, 1 or 255 = defective) produced manually or by
   another detection tool.
3. For each channel of the image being processed, a **sliding median filter** of size
   $2\cdot\texttt{radius}+1$ is computed over the whole image (`reflect` edge mode).
4. The final result replaces **only** the pixels flagged as defective with the median-filter value
   at that position; every other pixel is left completely unchanged.

If `map_path` is empty, the process is a **pass-through**: the image is returned unchanged
(a copy).

## Mathematics

Let $D(x,y) \in \{0,1\}$ be the defect indicator drawn from the map (`dmap[x,y] \neq 0`), and
$I_c(x,y)$ the input image for channel $c$. A sliding median is first computed over a square
window of side $n = 2r + 1$ (with $r$ = `radius`):

$$ M_c(x,y) = \operatorname{med}\Big(\, I_c(x', y') \;:\; (x',y') \in W_n(x,y) \,\Big), $$

where $W_n(x,y)$ is the $n \times n$ neighborhood centered at $(x,y)$ (mirror-reflected at the
edges). The output is a pixel-wise conditional replacement:

$$ I'_c(x,y) = \begin{cases} M_c(x,y) & \text{if } D(x,y) = 1 \\ I_c(x,y) & \text{otherwise.} \end{cases} $$

A median filter is used rather than a mean because it is **robust**: even if the immediate
neighborhood contains other defective pixels or impulsive noise, the median is only affected once
more than half the window is corrupted.

## Parameters

- **`map_path`** — *path*, default `""` (empty). Path to the defect map: an image where every
  **non-zero** pixel (on its first channel) marks a pixel to correct. If empty, no correction is
  applied.
- **`radius`** — *int*, default `1`, range `1`–`10`. Radius of the median neighborhood used to
  reconstruct each defective pixel; the effective window is $2\cdot\texttt{radius}+1$ pixels wide.

## Tips & pitfalls

> **Warning** — the defect map must have **exactly the same dimensions** as the images being
> corrected. A geometry mismatch (cropping, different binning) shifts the correction onto healthy
> pixels.

> **Note** — unlike `CosmeticCorrection`, no statistical threshold is involved here: the map is
> authoritative. An overly generous map (too many flagged pixels) locally smooths the image beyond
> what is actually needed.

- A defect map is typically built by thresholding a master dark or master bias (pixels far above
  or below the global median), then binarizing it.
- Too large a `radius` spreads the replacement over a wide neighborhood, which can smear fine
  detail adjacent to a defect; start at `1` and increase only if artifacts remain.
- For adaptive, per-pixel correction without a pre-built map, see `CosmeticCorrection`.

## See also

- [CosmeticCorrection](retina-doc://CosmeticCorrection) — statistical detection and automatic
  correction of hot/cold pixels.
- [PixelInterpolation](retina-doc://PixelInterpolation) — fills NaN / dead pixels via a Gaussian
  weighted convolution.
- [CosmicClip](retina-doc://CosmicClip) — cosmic-ray rejection (astroscrappy).
- [Superbias](retina-doc://Superbias) — smoothed master bias modeling.

## References

- PixInsight — *CosmeticCorrection* tool reference (defect list / master dark based detection).
- scipy.ndimage — *median_filter*, sliding median filter.
