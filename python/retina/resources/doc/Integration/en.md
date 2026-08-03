---
id: Integration
category: ImageIntegration
title: Integration (stacking)
brief: Combines several frames into one image, with robust sigma rejection (median + mad_std).
keywords: [integration, stacking, sigma rejection, master, mad_std]
related: [ImageCalibration, StarAlignment, FastIntegration, DrizzleIntegration]
icon: stack-2
references:
  - "PixInsight — ImageIntegration tool reference."
  - "astropy.stats — sigma_clip with median / mad_std estimators."
---

## Summary

`Integration` stacks several aligned exposures into a single image with a greatly improved
**signal-to-noise ratio**. A **robust sigma rejection** discards, pixel by pixel, outliers
(cosmic rays, satellites, hot pixels) before averaging. It is a **global** process: it reads a
list of files and creates a new window. It is also used to build **masters** (bias, dark, flat)
by robust averaging.

![A single frame — Integration](figures/single.webp)
![Six frames stacked — Integration](figures/stacked.webp)

*One bias frame, and the stack of six. Bias rather than lights, because the dataset carries a single light per filter and a bias frame is nothing but noise — so the pair shows exactly what stacking is for: six frames divide the noise by about the square root of six. Each has its own screen stretch, the effect being a change in the spread of the values rather than in their level.*

## Use cases

- **Stack a session's exposures** (after calibration and alignment) to gain SNR.
- **Build calibration masters** (average of biases/darks/flats).
- **Clean out intruders**: satellite trails, planes, cosmic rays, without a pure median.

## How it works

Frames are loaded and stacked into an $(N, H, W, C)$ cube. For each pixel position, the
algorithm computes **outlier-resistant** statistics — the **median** as center and the
**mad_std** (a standard deviation derived from the median absolute deviation) as spread — then
rejects samples outside $[\,\text{med} - \sigma_\text{low}\cdot s,\;
\text{med} + \sigma_\text{high}\cdot s\,]$. The output is the **mean of the kept samples**. If
none survive, it falls back to the plain mean.

## Mathematics

For a stack of values $\{x_i\}_{i=1}^{N}$ at a pixel position, estimate the robust center and
scale:

$$ \tilde{x} = \operatorname{med}(x_i), \qquad
   s = \operatorname{mad\_std}(x_i) = 1.4826 \cdot \operatorname{med}\!\big(|x_i - \tilde{x}|\big). $$

The factor $1.4826$ makes mad_std consistent with the standard deviation for a normal
distribution. A sample is **kept** if:

$$ \tilde{x} - \sigma_\text{low}\, s \;\le\; x_i \;\le\; \tilde{x} + \sigma_\text{high}\, s . $$

The integrated value is the mean of the kept samples:

$$ \bar{x} = \frac{1}{|K|}\sum_{i \in K} x_i, \qquad
   K = \{\, i : x_i \text{ kept} \,\}. $$

Using the median and mad_std (rather than mean/standard deviation) is essential: a single
intruder would inflate a classical standard deviation enough to **escape rejection**.

## Parameters

- **`frames`** — *pathlist*, default `[]`. Files to stack (already calibrated/aligned).
- **`rejection`** — *enum*, default `sigma`, choices: `none`, `sigma`. Outlier rejection type.
- **`sigma_low`** — *real*, default `3.0`, range `0`–`10`. Low-side rejection threshold (in robust $\sigma$).
- **`sigma_high`** — *real*, default `3.0`, range `0`–`10`. High-side rejection threshold.
- **`new_image_id`** — *str*, default `integration`. Identifier of the result window.

## Tips & pitfalls

> **Note** — integration assumes **aligned** frames (see `StarAlignment`) of identical
> geometry. Unregistered frames produce blur, not an SNR gain.

- Few frames (< 10): tight sigma thresholds reject too much; loosen `sigma_low/high`.
- For bias/dark/flat masters, sigma rejection removes transient stray pixels.

## See also

- [ImageCalibration](retina-doc://ImageCalibration) — prerequisite step (bias/dark/flat).
- [StarAlignment](retina-doc://StarAlignment) — register frames before stacking.
- [DrizzleIntegration](retina-doc://DrizzleIntegration) — drizzle integration (upsampling).

## References

- PixInsight — *ImageIntegration* tool reference.
- astropy.stats — *sigma_clip* with median / mad_std estimators.
