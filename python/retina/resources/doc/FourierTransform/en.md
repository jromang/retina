---
id: FourierTransform
category: Fourier
title: Fourier Transform
brief: Moves the image into the frequency domain — an amplitude spectrum for inspection, or a reversible complex representation.
keywords: [Fourier, FFT, spectrum, frequency, frequency domain, periodic patterns, phase]
related: [InverseFourierTransform, Convolution, Deconvolution, MultiscaleLinearTransform]
icon: wave-sine
references:
  - "PixInsight — FourierTransform / InverseFourierTransform tool reference."
  - "numpy.fft — Discrete Fourier Transform (fft2, fftshift)."
  - "Cooley, J. W. & Tukey, J. W. (1965) — An algorithm for the machine calculation of complex Fourier series."
---

## Summary

`FourierTransform` computes the **2D discrete Fourier transform** of each image channel via
`numpy.fft`. Depending on `mode`, it produces either a log-normalized, centered **amplitude
spectrum** meant for **visual inspection** (spotting periodic patterns, banding, sensor readout
artifacts), or a **full complex representation** (real and imaginary parts stacked as extra
channels) that allows exact reconstruction through `InverseFourierTransform`. This mirrors the
FourierTransform / InverseFourierTransform pair found in PixInsight.

![Source image — FourierTransform](figures/source.webp)
![Magnitude spectrum — FourierTransform](figures/spectrum.webp)

*The frame, and its magnitude spectrum. Not a before/after: the spectrum is another way of looking at the same data, where periodic structure stands out.*

## Use cases

- **Diagnose periodic patterns**: readout banding, poorly calibrated flat frames, filter moiré,
  autoguiding oscillations — all show up as characteristic peaks or streaks in the amplitude
  spectrum.
- **Prepare frequency-domain filtering**: switch to `mode="complex"`, manually manipulate the
  spectrum (attenuate a band or a peak), then return to the spatial domain with
  `InverseFourierTransform` for an exact round-trip.
- **Analyze noise texture** or the point-spread function by examining the spectral falloff,
  ahead of a `Deconvolution` or a `RestorationFilter`.
- **Teaching / verification**: confirm that a spatial-domain operation matches the expected
  frequency-domain behavior (convolution theorem).

## How it works

For each channel $k$ of the image, the operator computes the 2D FFT via `numpy.fft.fft2`, then
recenters the low frequencies to the middle of the spectrum with `numpy.fft.fftshift` (without
this shift the zero frequency would sit in the top-left corner, hard to read).

- In `magnitude` mode: the magnitude of the complex spectrum is taken, a `log1p` is applied
  (to compress the huge dynamic range between the DC component and high frequencies), then the
  result is normalized by the channel's maximum to land in `[0, 1]`, ready to display.
- In `complex` mode: the real and imaginary parts of the fftshifted spectrum are kept separately,
  stacked channel by channel into a `2·C`-channel image: `[re₀…re_{C-1}, im₀…im_{C-1}]`. No
  information is lost — `InverseFourierTransform` exactly undoes this layout (`ifftshift` then
  `ifft2`, taking the real part of the result) to recover the original spatial image, up to
  floating-point rounding.

## Mathematics

For an image channel $I(x, y)$ of size $H \times W$, the 2D discrete Fourier transform is:

$$ F(u, v) = \sum_{x=0}^{H-1} \sum_{y=0}^{W-1} I(x, y)\, e^{-2i\pi \left(\frac{ux}{H} + \frac{vy}{W}\right)} $$

$F(u, v)$ is generally **complex**: $F = \Re(F) + i\,\Im(F)$. The amplitude spectrum shown in
`magnitude` mode is:

$$ M(u, v) = \frac{\log\!\big(1 + |F(u, v)|\big)}{\max_{u,v} \log\!\big(1 + |F(u, v)|\big)}, \qquad
   |F(u, v)| = \sqrt{\Re(F)^2 + \Im(F)^2}. $$

The `log1p` compresses the dynamic range: the DC component $F(0,0)$ (proportional to the mean
pixel value) typically dominates high frequencies by several orders of magnitude, and would
otherwise remain invisible without logarithmic compression.

In `complex` mode, the produced image fully encodes $\Re(F)$ and $\Im(F)$ (after `fftshift`),
enabling exact reconstruction via the inverse transform:

$$ I(x, y) = \frac{1}{HW} \sum_{u=0}^{H-1} \sum_{v=0}^{W-1} F(u, v)\, e^{+2i\pi \left(\frac{ux}{H} + \frac{vy}{W}\right)}. $$

`InverseFourierTransform` reassembles $F = \Re(F) + i\,\Im(F)$, applies `ifftshift` (undoing the
recentering), then `ifft2`, and keeps only the real part of the result (theoretically zero on
the imaginary side for a real-valued source image, up to rounding error).

## Parameters

- **`mode`** — *enum*, default `magnitude`, choices `magnitude` / `complex`. Selects the output:
  `magnitude` produces a log-normalized amplitude spectrum in `[0,1]`, bounded, meant for visual
  inspection (same channel count as the input). `complex` produces a `2·C`-channel image (real
  then imaginary, unbounded) meant for frequency-domain manipulation followed by reconstruction
  via `InverseFourierTransform`.

## Tips & pitfalls

> **Warning** — `complex` mode produces an image with **unbounded** values (spectrum
> amplitudes, potentially very large or negative). Do not display it directly as a normal image
> or save it as a final result: it is an intermediate exchange format meant for
> `InverseFourierTransform`.

> **Note** — the `magnitude` amplitude spectrum is **irreversible**: the phase (carried by the
> ratio of real to imaginary parts) is discarded, yet it holds most of the image's structural
> information. Use `magnitude` for inspection only, never to recover the original image.

- Periodic patterns (banding, moiré) show up as **isolated peaks or streaks** outside the
  central lobe of the spectrum — zoom into the displayed spectrum to spot them.
- The DC component (zero frequency) always sits at the **exact center** of the image after
  `fftshift`: it is the brightest point of the spectrum, with no diagnostic value on its own.
- For manual frequency filtering (attenuating a band), operate on the `complex` output with
  `PixelMath` or in the console before feeding it back through `InverseFourierTransform`.

## See also

- [InverseFourierTransform](retina-doc://InverseFourierTransform) — exact reconstruction from the `complex` output.
- [Convolution](retina-doc://Convolution) — spatial operation equivalent to a frequency-domain multiplication.
- [Deconvolution](retina-doc://Deconvolution) — restoration built on the frequency domain.
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — scale decomposition, an alternative to Fourier filtering.

## References

- PixInsight — *FourierTransform* / *InverseFourierTransform* tool reference.
- numpy.fft — *Discrete Fourier Transform* (`fft2`, `fftshift`).
- Cooley, J. W. & Tukey, J. W. (1965) — *An algorithm for the machine calculation of complex Fourier series*.
