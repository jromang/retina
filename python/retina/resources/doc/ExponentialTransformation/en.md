---
id: ExponentialTransformation
category: IntensityTransformations
title: Exponential Transformation
brief: Simple non-linear power-law stretch (PIP brightens, SMI darkens), PixInsight-style.
keywords: [exponential, power law, gamma, PIP, SMI, stretch, non-linear]
related: [HistogramTransformation, ArcsinhStretch, AutoHistogram, CurvesTransformation]
icon: math-function
references:
  - "PixInsight — ExponentialTransformation tool reference."
---

## Summary

`ExponentialTransformation` applies a simple **power law** (gamma) to the pixels, in one of two
directions inherited from PixInsight: **PIP** (*Power of Inverted Pixels*), which brightens the
image by expanding the shadows, or **SMI**, which darkens it by compressing the mid-tones and
highlights. A single `order` parameter controls the strength of the effect. This is the most
basic non-linear stretch in the catalog — no adjustable black/white point, no color protection,
unlike `HistogramTransformation` or `ArcsinhStretch`.

![Before — ExponentialTransformation](figures/before.webp)
![After — ExponentialTransformation](figures/after.webp)

*The linear frame as stored, and the same frame after the SMI curve at order 0.5.*

## Use cases

- **Quickly brighten** a dark image (PIP) without going through a full three-slider MTF setup.
- **Darken/compress** overpowering highlights (SMI), for instance the core of a nebula or galaxy
  that has already been stretched hard.
- **Fine gamma tweak** at the end of processing, when a small contrast nudge is enough and a full
  curve would be overkill.
- **Pipeline building block**: an `order` close to `1.0` (near-identity) lets the process sit in
  a recipe with negligible effect, to be tuned later.

## How it works

The process first clips the pixels to `[0, 1]`, then applies **one of two power laws,
per channel and independently**, chosen via `type`:

- **PIP** (*Power of Inverted Pixels*): pixels are inverted ($1-x$), raised to the `order`
  power, then re-inverted. Both endpoints $0$ and $1$ stay fixed; for `order > 1`, the slope at
  the black point equals `order`, which **expands the shadows** (brightens) while leaving
  highlights nearly untouched.
- **SMI**: a plain direct power $x^{\text{order}}$. For `order > 1`, every intermediate value is
  pulled down — the image **darkens and compresses**, sparing the extremes ($0$ and $1$ stay
  fixed).

No explicit color protection is applied (unlike `ArcsinhStretch` or `AdaptiveStretch`, which
derive the stretch factor from luminance): each RGB channel goes through the same power law
independently, which can slightly shift the hue of saturated color pixels.

## Mathematics

Let $x \in [0,1]$ be a (clipped) pixel value and $p = $ `order`. The two transfer functions are:

$$
f_{\text{PIP}}(x) = 1 - (1-x)^{p}, \qquad
f_{\text{SMI}}(x) = x^{p}.
$$

They are related by the $x \mapsto 1-x$ symmetry: $f_{\text{PIP}}(x) = 1 - f_{\text{SMI}}(1-x)$.
Both fix $0$ and $1$ and are strictly monotone on $[0,1]$ for $p>0$. Their slope at the black
point gives the intuition for the effect:

$$
f_{\text{PIP}}'(0) = p, \qquad f_{\text{SMI}}'(0) =
\begin{cases} 0 & \text{if } p>1 \\ +\infty & \text{if } p<1 \end{cases}.
$$

Concretely: with $p>1$, PIP has a steep slope at the black point → it **expands the shadows**
(brightens), while SMI has a zero slope at the black point and pulls intermediate values down →
it **darkens/compresses**. With $0<p<1$, both effects flip (PIP darkens, SMI brightens). At
$p=1$, both functions are the identity.

## Parameters

- **`type`** — *enum*, default `PIP`, choices: `PIP`, `SMI`. Direction of the transformation:
  `PIP` (*Power of Inverted Pixels*) brightens by expanding the shadows; `SMI` darkens by
  compressing mid-tones and highlights.
- **`order`** — *real*, default `1.0`, range `0.1`–`6.0`. Exponent of the power law. At `1.0`,
  the transformation is neutral (identity). The further it moves from `1.0`, the stronger the
  effect (brightening or darkening depending on `type`).

## Tips & pitfalls

> **Warning** — the transformation is **destructive** (like `HistogramTransformation`) and has
> **no color protection**: on a heavily stretched RGB image, a high `order` can slightly shift
> the hue of saturated areas, since there is no common factor derived from luminance.

- For an order well below `1.0`, the effect of `PIP` and `SMI` flips (PIP then darkens, SMI then
  brightens) — always check visually rather than trusting the name.
- Unlike `HistogramTransformation`, there is no adjustable black or white point: fix the
  histogram framing upstream if the image is not already well spread over `[0,1]`.
- For a color-preserving stretch on linear data heavily bunched near zero, prefer
  `ArcsinhStretch`, which derives its factor from luminance.

## See also

- [HistogramTransformation](retina-doc://HistogramTransformation) — black/mid/white point stretch (MTF).
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — color-preserving non-linear stretch.
- [AutoHistogram](retina-doc://AutoHistogram) — auto-stretch baked into the pixels.
- [CurvesTransformation](retina-doc://CurvesTransformation) — free-curve tonal control.

## References

- PixInsight — *ExponentialTransformation* tool reference.
