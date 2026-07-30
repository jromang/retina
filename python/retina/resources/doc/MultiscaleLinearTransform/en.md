---
id: MultiscaleLinearTransform
category: MultiscaleProcessing
title: Multiscale Linear Transform (à trous wavelets)
brief: Decomposes the image into starlet (à trous, B3-spline) wavelet detail layers to denoise or enhance per scale, then reconstructs.
keywords: [wavelets, starlet, à trous, B3-spline, multiscale, denoising, soft thresholding]
related: [MultiscaleMedianTransform, HDRMultiscaleTransform, WaveletDenoise, UnsharpMask]
icon: stack
references:
  - "Starck, J.-L. & Murtagh, F. — Astronomical Image and Data Analysis (à trous wavelet transform)."
  - "PixInsight — ATrousWaveletTransform / MultiscaleLinearTransform tool reference."
  - "astropy.stats.mad_std — robust standard deviation estimator."
---

## Summary

`MultiscaleLinearTransform` (MLT) applies the **starlet wavelet transform** (the "à trous",
i.e. *with holes*, transform, using a B3-spline kernel): it decomposes the image into a stack
of **detail layers** at increasing spatial scales (fine structures → large structures), plus
a low-frequency **residual**. Each layer can then be attenuated, amplified, or denoised
independently, before reconstruction by simple summation. It is the fundamental linear tool
for selective denoising and scale-specific structure enhancement — the direct counterpart of
PixInsight's *ATrousWaveletTransform* / *MultiscaleLinearTransform*.

## Use cases

- **Denoise without blurring**: attenuate, by soft thresholding, the noise concentrated in the
  finest layer (scale 1), without touching structures at coarser scales.
- **Enhance structures at a chosen scale** (thin nebula filaments, galaxy arms) by boosting the
  corresponding layer's `bias` above 1.
- **Suppress an unwanted scale** (background grain, JPEG-source compression artifact) by
  setting its `bias` below 1, or to 0 to remove it entirely.
- Serve as a **building block** for more elaborate treatments (HDRMultiscaleTransform,
  multiscale denoising, structure/noise separation) that reuse the same decomposition.

## How it works

For each channel, the decomposition is an **"à trous"** algorithm (*undecimated*, hence
redundant but perfectly reconstructible):

1. Start from the input channel image $c_0$.
2. At each scale $j = 0, \dots, J-1$, smooth $c_j$ with the **B3-spline** kernel
   `[1, 4, 6, 4, 1] / 16` (separable, applied along rows then columns), **dilated** by a
   factor $2^j$ — zeros ("holes") are inserted between the taps to double the kernel's reach
   at each scale without subsampling the image.
3. The **detail layer** at scale $j$ is the difference between the signal before and after
   that smoothing: $w_j = c_j - c_{j+1}$. The smoothed $c_{j+1}$ becomes the starting point
   for the next scale.
4. After `scales` iterations, what remains is a **residual** $r = c_J$ (the large-scale trend,
   free of detail).
5. Each layer is then adjusted: layer 0 (the finest, dominated by photon/read noise) undergoes
   **soft thresholding** if `noise_threshold > 0`, and all layers are multiplied by their
   respective `bias` (1 by default, i.e. unchanged).
6. **Reconstruction**: the output image is simply the sum of the adjusted layers and the
   residual — the key property of the à trous transform, which guarantees exact reconstruction
   when all biases equal 1 and no thresholding is applied.

## Mathematics

Let $h = \tfrac{1}{16}[1,4,6,4,1]$ be the 1D B3-spline kernel, and $h_j$ its **dilated**
version at scale $j$ (the 5 taps spaced $2^j$ pixels apart, zeros elsewhere). The 2D smoothing
at scale $j$ is the separable convolution $\ast_2$ (rows then columns, reflected border):

$$ c_0 = I, \qquad c_{j+1} = c_j \ast_2 h_j \;\; (j = 0, \dots, J-1). $$

The detail layer at scale $j$ and the final residual are:

$$ w_j = c_j - c_{j+1}, \qquad r = c_J . $$

The telescoping sum guarantees exact reconstruction of the input image:

$$ I = \sum_{j=0}^{J-1} w_j + r . $$

Denoising of the finest layer ($j=0$) uses a **robust estimator** of the noise standard
deviation, `mad_std` (scaled median absolute deviation, $1.4826 \cdot \operatorname{med}|w_0
- \operatorname{med}(w_0)|$), followed by **soft thresholding**:

$$ t = \texttt{noise\_threshold} \cdot \operatorname{mad\_std}(w_0), \qquad
   w_0' = \operatorname{sign}(w_0) \cdot \max(|w_0| - t,\; 0). $$

Every layer (including $w_0'$) is finally weighted by its bias $b_j$ (`bias[j]`, or $1$ if not
supplied) before the final sum:

$$ I_{\text{out}} = \sum_{j=0}^{J-1} b_j\, w_j + r, \quad \text{clipped to } [0,1]. $$

## Parameters

- **`scales`** — *int*, default `5`, range `1`–`12`. Number of decomposition scales $J$
  (number of detail layers produced, plus the residual). More scales let you reach larger
  structures; compute cost grows linearly with `scales`.
- **`bias`** — *floatlist*, default `[]` (empty list). Multiplier applied to each detail layer,
  in scale order (`bias[0]` = finest scale). Any scale without a supplied value keeps a bias of
  `1.0` (faithful reconstruction on that layer). `0.0` removes the layer entirely, `>1.0`
  amplifies its structures.
- **`noise_threshold`** — *real*, default `0.0`, range `0`–`10`. Denoising threshold, expressed
  as a multiple of the noise `mad_std`, applied **only to layer 0** (the finest) via soft
  thresholding. `0.0` disables denoising.

## Tips & pitfalls

> **Warning** — too high a `noise_threshold` also crushes faint stars and tenuous structures
> that live at scale 1: start low (1–3) and visually inspect the difference image (layer 0
> before/after thresholding).

> **Note** — with `bias` empty and `noise_threshold = 0.0`, the transform is an **exact
> identity** (decomposition + reconstruction with no loss): a safe starting point before tuning
> parameters scale by scale.

- The transform is **redundant** (undecimated): every layer has the same resolution as the
  input image, which makes masked work easy but costs memory for large `scales` on large
  images.
- For non-linear denoising that is more robust at edges (fewer ringing artifacts around
  stars), prefer `MultiscaleMedianTransform`, which uses an à-trous median filter instead of
  the B3-spline kernel.
- For a more targeted, single-pass structure enhancement (without explicitly decomposing into
  layers), `UnsharpMask` offers a simpler single-scale alternative.

## See also

- [MultiscaleMedianTransform](retina-doc://MultiscaleMedianTransform) — same principle with an
  à-trous median filter, more robust at edges.
- [HDRMultiscaleTransform](retina-doc://HDRMultiscaleTransform) — reuses the starlet
  decomposition to compress the global dynamic range.
- [WaveletDenoise](retina-doc://WaveletDenoise) — wavelet-based denoising oriented toward image
  quality rather than manual per-scale control.
- [UnsharpMask](retina-doc://UnsharpMask) — single-scale structure enhancement via a blurred mask.

## References

- Starck, J.-L. & Murtagh, F. — *Astronomical Image and Data Analysis* (à trous wavelet
  transform).
- PixInsight — *ATrousWaveletTransform* / *MultiscaleLinearTransform* tool reference.
- astropy.stats.mad_std — robust standard deviation estimator.
