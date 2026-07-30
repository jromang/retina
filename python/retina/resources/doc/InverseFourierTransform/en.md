---
id: InverseFourierTransform
category: Fourier
title: Inverse Fourier Transform
brief: Exactly reconstructs the spatial image from the complex representation produced by FourierTransform.
keywords: [Fourier, inverse FFT, frequency domain, reconstruction, round-trip, phase]
related: [FourierTransform, Convolution, Deconvolution, MultiscaleLinearTransform]
icon: wave-sine
references:
  - "PixInsight — FourierTransform / InverseFourierTransform tool reference."
  - "numpy.fft — Discrete Fourier Transform (ifft2, ifftshift)."
  - "Cooley, J. W. & Tukey, J. W. (1965) — An algorithm for the machine calculation of complex Fourier series."
---

## Summary

`InverseFourierTransform` closes the loop opened by `FourierTransform` in `complex` mode: it
takes the `2·C`-channel image ([real parts | imaginary parts], fftshifted) and reconstructs the
original spatial image **exactly**, channel by channel. It is the equivalent of PixInsight's
`InverseFourierTransform`: with no parameters, it applies a mathematically well-defined operation
that simply inverts the forward FFT, with no approximation beyond floating-point rounding.

## Use cases

- **Close a frequency-domain filtering pass**: after switching an image to `mode="complex"` with
  `FourierTransform`, modifying it (attenuating a band, removing a periodic peak) via `PixelMath`
  or in the console, run it back through `InverseFourierTransform` to return to the spatial
  domain and continue processing normally.
- **Verify a round-trip**: confirm that `FourierTransform(mode='complex')` followed by
  `InverseFourierTransform` faithfully restores the original image (regression testing, teaching,
  debugging a custom frequency-domain filter).
- **Frequency-domain restoration**: final step of a manually built deconvolution or Wiener
  filtering pipeline constructed in the Fourier domain.

## How it works

For each of the $C$ output channels $k$, the operator reads the real part from input channel $k$
and the imaginary part from channel $C+k$ (the convention imposed by
`FourierTransform(mode='complex')`), recomposes the complex spectrum, undoes the forward
recentering (`fftshift`) with `numpy.fft.ifftshift`, then applies the 2D inverse FFT
(`numpy.fft.ifft2`). Only the **real part** of the result is kept: for a real-valued original
image, the imaginary part of the reconstruction is zero up to floating-point rounding error, so
discarding it loses no information.

The process requires an even number of input channels (`2·C`); an input with an odd channel
count — a sign it did not come from `FourierTransform(mode='complex')` — triggers an explicit
error instead of a silently wrong result.

## Mathematics

Let $F(u, v) = \Re(F) + i\,\Im(F)$ be the fftshifted complex spectrum of a channel, as encoded by
`FourierTransform(mode='complex')` in channels $k$ (real) and $C+k$ (imaginary). Reconstruction
proceeds in three steps:

1. **Recompose** the complex number from the two channels:
   $$ F(u, v) = I_{\text{re}}(u, v) + i\, I_{\text{im}}(u, v). $$
2. **Undo the recentering** (`ifftshift`), which moves the zero frequency back to the array's
   top-left corner, the convention expected by the inverse FFT.
3. **2D inverse Fourier transform**, which recovers the spatial signal:
   $$ I(x, y) = \frac{1}{HW} \sum_{u=0}^{H-1} \sum_{v=0}^{W-1} F(u, v)\,
      e^{+2i\pi \left(\frac{ux}{H} + \frac{vy}{W}\right)}, $$
   of which only the real part is kept: $I(x, y) \leftarrow \Re\big(I(x, y)\big)$.

This sequence of operations is the exact inverse of `FourierTransform`'s (`fft2` then
`fftshift`): composing the two yields the identity, up to `float32` precision,
$$ \texttt{InverseFourierTransform}\big(\texttt{FourierTransform}_{\text{complex}}(I)\big) = I. $$

## Parameters

This process has **no parameters**. Its behavior is fully determined by the input data: the
geometry and spectral content encoded in the `(H, W, 2·C)` image produced by
`FourierTransform(mode='complex')` are sufficient to define the reconstruction, with no user
setting involved.

## Tips & pitfalls

> **Warning** — the input must come from `FourierTransform(mode='complex')` (or exactly follow
> its convention: real then imaginary, fftshifted). Applying this process to an ordinary image,
> or to the **magnitude** spectrum (`mode='magnitude'`), produces a meaningless result — the
> magnitude mode has irretrievably lost the phase and is not invertible.

> **Note** — the output channel count is **half** the input's (`C` vs `2·C`). An input with an
> odd channel count is rejected with an explicit error.

- For manual frequency-domain filtering between the two steps, stay consistent: any modification
  of the spectrum should preserve Hermitian symmetry if a clean real result is wanted (otherwise
  the discarded imaginary part held non-negligible information).
- The full round-trip (`FourierTransform` → `InverseFourierTransform`) is **exact** up to
  `float32` rounding noise: useful as a reference test to validate any code manipulating the
  spectrum in between the two steps.

## See also

- [FourierTransform](retina-doc://FourierTransform) — forward transform, source of the `complex` representation.
- [Convolution](retina-doc://Convolution) — spatial operation equivalent to a frequency-domain multiplication.
- [Deconvolution](retina-doc://Deconvolution) — restoration relying on the frequency domain.
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — scale decomposition, an alternative to Fourier filtering.

## References

- PixInsight — *FourierTransform* / *InverseFourierTransform* tool reference.
- numpy.fft — *Discrete Fourier Transform* (`ifft2`, `ifftshift`).
- Cooley, J. W. & Tukey, J. W. (1965) — *An algorithm for the machine calculation of complex Fourier series*.
