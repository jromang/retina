---
id: SampleFormatConversion
category: Image
title: Sample Format Conversion
brief: Simulates quantization to N bits per channel (8/16/32) while staying float32 in memory.
keywords: [quantization, bit depth, bits, integer, rounding, banding, precision]
related: [Rescale, Binarize, Statistics, HistogramTransformation]
icon: transform
references:
  - "PixInsight — SampleFormatConversion process reference."
  - "Numpy — numpy.rint / uniform quantization of a signal."
---

## Summary

`SampleFormatConversion` simulates the effect of **saving as an N-bit integer format** (8, 16
or 32) on pixel values, without ever changing the image's actual storage type: internally,
Retina always works in `float32`. The process **rounds** each sample to the nearest
quantization level for a `bits`-bit-per-channel format, then renormalizes it into `[0, 1]`.
It is the diagnostic/pedagogical counterpart of PixInsight's `SampleFormatConversion`, useful
for **previewing precision loss** before an integer TIFF/FITS export, or for deliberately
reproducing banding in a test.

## Use cases

- **Anticipate an 8- or 16-bit export**: see the banding (staircase contours) that an integer
  save would introduce on a heavily stretched sky-background gradient, before actually
  committing to that choice at save time.
- **Diagnose precision loss** that already occurred on a file acquired/converted to integer,
  by reproducing the artifact to compare it visually against the 32-bit float version.
- **Testing/teaching**: illustrate the difference between bit depth and a sensor's actual
  dynamic range, or generate synthetic quantized data for unit tests.

## How it works

The `bits` parameter selects a number of quantization levels $L = 2^{\text{bits}}$. For
`bits = 32`, the process is a **pass-through**: the `float32` data is copied unchanged (32-bit
float is not quantized here, since the native depth already exceeds what a 32-bit integer
would practically add for image data). For `8` or `16` bits, each sample is:

1. **clipped** to `[0, 1]` (Retina's normalized working space);
2. **multiplied** by the number of available steps ($2^{\text{bits}} - 1$) and **rounded** to
   the nearest integer — simulating storage as an unsigned `bits`-bit integer;
3. **divided back** by the same factor to return to `[0, 1]`, where the result is cast back
   and stored as `float32`.

The image therefore remains a regular Retina floating-point image (chainable, maskable), but
its values can now only take $2^{\text{bits}}$ distinct levels per channel — exactly the effect
a real `bits`-bit integer save would have.

## Mathematics

Let $x \in [0,1]$ be a sample value and $b$ = `bits`. The number of representable levels and
the associated quantization step are:

$$ L = 2^{b} - 1, \qquad \Delta = \frac{1}{L}. $$

The quantized output is:

$$ q(x) = \frac{1}{L}\,\operatorname{round}\!\big(L \cdot \operatorname{clip}(x, 0, 1)\big). $$

Assuming the rounding error is uniform on $[-\Delta/2, \Delta/2]$, the introduced quantization
noise has theoretical variance:

$$ \sigma_q^2 = \frac{\Delta^2}{12} = \frac{1}{12\,(2^{b}-1)^2}. $$

At `bits = 8`, $\Delta \approx 1/255$ and $\sigma_q \approx 1.1\times10^{-3}$ — clearly visible
as steps on a smooth, heavily stretched gradient. At `bits = 16`, $\Delta \approx 1/65535$ and
$\sigma_q \approx 4.4\times10^{-6}$, generally well below the sensor's photon noise and
therefore invisible in practice.

## Parameters

- **`bits`** — *enum*, default `16`, choices: `8`, `16`, `32`. Simulated bit depth per channel.
  `8` and `16` apply the quantization described above; `32` leaves the `float32` data unchanged
  (plain copy).

## Tips & pitfalls

> **Warning** — this operation is **destructive**: the intermediate levels lost through
> rounding are not recoverable (short of undoing via the view's history). Do not apply it too
> early in a linear-processing pipeline, or you risk amplifying banding under later aggressive
> stretches.

- Banding introduced by 8-bit quantization is strongly amplified by `HistogramTransformation`
  or any nonlinear stretch applied afterward: always test quantization **after** the final
  stretch, not before.
- To objectively check the effect, compare `Statistics` before/after: the number of unique
  values per channel drops to at most $2^{\text{bits}}$.
- This process does not replace the actual export format choice (8/16-bit TIFF, integer FITS):
  it only **previews** the effect while keeping the image usable as `float32` within Retina.

## See also

- [Rescale](retina-doc://Rescale) — renormalizes the dynamic range before quantization.
- [Binarize](retina-doc://Binarize) — extreme case of quantization to 1 bit (thresholding).
- [Statistics](retina-doc://Statistics) — measure the quantization noise introduced.
- [HistogramTransformation](retina-doc://HistogramTransformation) — the stretch that reveals banding.

## References

- PixInsight — *SampleFormatConversion* process reference.
- Numpy — *numpy.rint* / uniform quantization of a signal.
