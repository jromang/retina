---
id: HistogramTransformation
category: IntensityTransformations
title: Histogram Transformation
brief: Stretches and repositions tones through a shadows/midtones/highlights transfer function (MTF).
keywords: [histogram, stretch, MTF, midtones, black point, gamma]
related: [CurvesTransformation, AutoHistogram, MaskedStretch, ArcsinhStretch]
icon: chart-histogram
references:
  - "PixInsight — HistogramTransformation tool reference."
  - "Conejero, J. — Midtones Transfer Function (MTF)."
---

## Summary

`HistogramTransformation` applies a **tonal transfer function** to the pixels, defined by
three sliders: the **black point** (shadows), the **midtones** (which controls perceived
gamma) and the **white point** (highlights). It is the fundamental stretching tool: it turns
a linear image (dark, bunched near zero) into a display-ready one, or finely tunes the
contrast and brightness of an already-stretched image.

Unlike the STF (ScreenTransferFunction), which only affects **display**, this transformation
is **destructive**: it rewrites pixel values into the view history.

## Use cases

- **"Bake" an auto-stretch**: commit the STF's non-destructive stretch into the pixels
  (see `HistogramTransformation.from_stf_channel`) once the composition is settled.
- **Set the black point** to anchor the sky background without clipping stars.
- **Lift the midtones** (faint nebulosity) by lowering the midtones slider.
- **Recover highlights** by lowering the white point when star cores saturate.

## How it works

The operator works in two steps, per channel:

1. **Linear remap** of the `[shadows, highlights]` range onto `[0, 1]`, with clipping:
   anything below the black point becomes 0, anything above the white point becomes 1.
2. **MTF application** (Midtones Transfer Function) parameterized by `midtones`, which curves
   the response to brighten (midtones < 0.5) or darken (midtones > 0.5) the mid-tones.

## Mathematics

Let $x$ be a pixel value in $[0,1]$, $s$ = `shadows`, $h$ = `highlights`, $m$ = `midtones`.
First compute the remapped value:

$$ x_n = \operatorname{clip}\!\left(\frac{x - s}{\,h - s\,},\; 0,\; 1\right) $$

then apply the **midtones transfer function**:

$$ \operatorname{mtf}(m, x_n) = \frac{(m - 1)\,x_n}{(2m - 1)\,x_n - m} $$

This function maps $0 \mapsto 0$ and $1 \mapsto 1$, and sends the input $m$ to the output
$0.5$: the midtones slider therefore directly sets the value that becomes mid-gray. The
limiting cases are continuous: $m \to 0$ brightens to the extreme ($\operatorname{mtf}\to 1$),
$m \to 1$ darkens to the extreme ($\operatorname{mtf}\to 0$), and $m = 0.5$ is the identity.

## Parameters

- **`shadows`** — *real*, default `0.0`, range `0`–`1`. Black point: input value mapped to 0.
  Any lower pixel is clipped to black.
- **`midtones`** — *real*, default `0.5`, range `0`–`1`. Mid-tone balance (gamma). Below 0.5
  the image brightens, above it darkens.
- **`highlights`** — *real*, default `1.0`, range `0`–`1`. White point: input value mapped to 1.
  Any higher pixel is clipped to white.

## Tips & pitfalls

> **Warning** — too high a black point permanently removes faint nebulosity halos. Check the
> histogram afterwards and work under a mask if needed.

- For a gentle background-preserving stretch, prefer small repeated steps over one hard crush.
- On linear data, `AutoHistogram` or an STF auto-stretch give a good starting point to refine here.

## See also

- [CurvesTransformation](retina-doc://CurvesTransformation) — free-curve tonal control.
- [MaskedStretch](retina-doc://MaskedStretch) — iterative star-preserving stretch.
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — color-preserving stretch.

## References

- PixInsight — *HistogramTransformation* tool reference.
- Conejero, J. — *Midtones Transfer Function (MTF)*.
