---
id: Superbias
category: Calibration
title: Superbias
brief: "Models a master bias as a smooth, noise-free residual via starlet decomposition (keeps only large-scale structure)."
keywords: [superbias, master bias, starlet, a trous, denoising, calibration, wavelets]
related: [Integration, ImageCalibration, MultiscaleLinearTransform, MultiscaleMedianTransform]
icon: photo
references:
  - "PixInsight — SuperBias script/process reference."
  - "Starck, J.-L. & Murtagh, F. — Astronomical Image and Data Analysis (starlet / a trous wavelet transform)."
  - "Starck, J.-L., Fadili, J., Murtagh, F. — The Undecimated Wavelet Decomposition and its Reconstruction."
---

## Summary

`Superbias` turns a raw master bias (the mean/median of a stack of bias frames) into a
**smooth, noise-free** version, keeping only its **large-scale structure** (amplifier glow
patterns, readout banding, bias gradients) and discarding the fine readout noise that a plain
average never fully removes. It is the equivalent of PixInsight's *SuperBias* script: instead
of using the stacked bias as-is for calibration, this smoothed model is used, which avoids
injecting extra noise into calibrated lights.

## Use cases

- **Build a high-quality master bias** from an already-stacked bias pile (`Integration`),
  before feeding it into `ImageCalibration`.
- **Reduce the noise added by bias subtraction**: a raw bias, even averaged over dozens of
  frames, keeps a residual of readout noise that propagates into every calibrated light. The
  superbias removes that residual while preserving the sensor's fixed patterns (hot columns,
  amplifier glow, corner glow).
- **Isolate the sensor's fixed-pattern structure** for diagnostics (highlighting readout
  patterns independently of random thermal noise).

## How it works

The algorithm applies a **starlet decomposition** (isotropic, undecimated à trous wavelet
transform) channel by channel, then keeps only the **residual** of the decomposition — the
smoothest version of the image, obtained after zeroing out the `noise_layers` finest (and
therefore noisiest) detail layers.

Concretely, for each channel:

1. The image is iteratively convolved with a dilated (à trous) B3-spline kernel at growing
   scales $2^0, 2^1, \dots, 2^{n-1}$, where $n$ = `noise_layers`.
2. At each iteration $j$, the **detail layer** is the difference between the current
   approximation and the smoother approximation obtained by the convolution at scale $j$.
3. After $n$ iterations, a **residual** remains — the image smoothed at scale $2^{n}$ — which
   only retains structures whose characteristic size exceeds that scale.

Only this residual is returned (the detail layers, which carry the fine pixel-to-pixel noise,
are discarded): that is the "superbias". The result is then clipped to `[0, 1]`.

## Mathematics

The starlet transform uses the 1D B3-spline kernel $h = \tfrac{1}{16}(1, 4, 6, 4, 1)$, separable
in 2D (successive convolution along rows then columns). At scale $j$, this kernel is dilated by
inserting $2^j - 1$ zeros between its coefficients (the à trous algorithm), yielding a low-pass
filter $h_j$ of growing support without downsampling.

Writing $c_0 = I$ for the input image (per channel), the algorithm iterates for
$j = 0, \dots, n-1$:

$$ c_{j+1} = h_j * c_j, \qquad w_{j+1} = c_j - c_{j+1}, $$

where $w_{j+1}$ is the detail layer at scale $j{+}1$ and $c_{j+1}$ the smoothed approximation
that feeds the next iteration. The exact reconstruction of the original image would be:

$$ I = c_n + \sum_{j=1}^{n} w_j . $$

`Superbias` keeps only the first term, the **residual** $c_n$:

$$ I_{\text{superbias}} = \operatorname{clip}(c_n,\; 0,\; 1). $$

The layers $w_1, \dots, w_n$, which carry most of the high-frequency readout noise (correlated
over at most a few pixels), are discarded. The larger $n$ = `noise_layers`, the higher the
cutoff scale $2^n$ and the more aggressive the smoothing: the result converges toward a nearly
constant image that retains only the broadest gradients.

## Parameters

- **`noise_layers`** — *int*, default `6`, range `1`–`12`. Number of starlet detail layers
  zeroed out before reconstruction. A low value (1–2) removes only the finest pixel-to-pixel
  noise and keeps fairly small patterns (columns, amplifier blocks); a high value (8–12)
  smooths much more aggressively and keeps only very large-scale gradients, at the risk of
  erasing genuine medium-scale readout patterns.

## Tips & pitfalls

> **Warning** — apply `Superbias` to an already **integrated** bias (`Integration` over a stack
> of dozens of bias frames), never to a single bias frame: on a single exposure, starlet
> smoothing merely blurs the noise, with no solid statistical basis to separate fixed signal
> from random noise.

> **Note** — too large a `noise_layers` value can erase genuine fixed structures (medium-scale
> amplifier patterns, corner glow) that you would want to keep in the calibration master.
> Visually compare the superbias against the raw integrated bias (difference via `PixelMath`)
> before settling on the value.

- The resulting superbias is used exactly like a regular master bias in `ImageCalibration`
  (the bias parameter).
- Since `Superbias` operates channel by channel, it can be applied directly to a color or CFA
  bias without prior demosaicing when the sensor's channels allow it (see `SplitCFA` to process
  each Bayer site separately if needed).

## See also

- [Integration](retina-doc://Integration) — stacks the raw bias pile before modeling.
- [ImageCalibration](retina-doc://ImageCalibration) — consumes the master bias (superbias or not).
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — the same starlet
  transform, with independent control per scale.
- [MultiscaleMedianTransform](retina-doc://MultiscaleMedianTransform) — non-linear (median)
  variant of the multiscale decomposition.

## References

- PixInsight — *SuperBias* script/process reference.
- Starck, J.-L. & Murtagh, F. — *Astronomical Image and Data Analysis* (starlet / à trous wavelet transform).
- Starck, J.-L., Fadili, J., Murtagh, F. — *The Undecimated Wavelet Decomposition and its Reconstruction*.
