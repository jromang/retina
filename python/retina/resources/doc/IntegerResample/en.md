---
id: IntegerResample
category: Geometry
title: Integer Resample
brief: Shrinks or enlarges the image by an exact integer factor via averaged/summed binning or pixel replication.
keywords: [binning, downsampling, upsampling, block_reduce, flux-preserving, resolution]
related: [Resample, Crop, Integration, BackgroundExtraction]
icon: grid-4x4
references:
  - "PixInsight — IntegerResample tool reference."
  - "astropy.nddata.block_reduce — block reduction by integer factor."
---

## Summary

`IntegerResample` changes an image's resolution by an **exact integer factor** `factor`, in
either direction: when shrinking (*downsample*), it groups `factor × factor` pixel blocks into
one by **binning** (average or sum); when enlarging (*upsample*), it **replicates** each pixel
into an identical `factor × factor` block (pure nearest-neighbor, no interpolation). Unlike
`Resample`, which accepts any real scale factor with interpolation, `IntegerResample` only
handles integer ratios — it's the classic **software binning** tool of astrophotography.

## Use cases

- **Simulate sensor binning** (2×2, 3×3…) after the fact on data acquired at 1×1, to reduce
  apparent read noise and file size at the cost of resolution.
- **Quickly preview** a very large image (mosaic, high-resolution master) by shrinking it by
  an integer factor before a heavy processing step or a web export.
- **Bin pixels before integrating** very noisy frames (low per-pixel SNR), when native
  resolution carries no usable information anyway.
- **Enlarge a binned mask or defect map** to re-align it with a full-resolution image without
  blurring the edges (exact replication).

## How it works

Processing depends on `mode`:

- **`upsample`** — each pixel is duplicated `factor` times along both axes (`numpy.repeat` on
  rows then columns), producing an image `factor` times larger in width and height, with no
  smoothing whatsoever.
- **`downsample`** — the image is first **cropped** to the largest multiple of `factor` not
  exceeding its dimensions (the trailing excess pixels are dropped), then split into
  `factor × factor` blocks aggregated according to `downsample_op`:
  - `average` — mean of the block (reshape + `mean` over the block axes); this is the
    radiometric equivalent of sensor binning, which **reduces noise** per output pixel without
    changing the value scale.
  - `sum` — sum of the block (via `astropy.nddata.block_reduce`), which **preserves total
    flux** — the correct choice for data meant for photometric measurement — with a final
    clip to `[0, 1]` since the sum can exceed a normalized image's range.

If `factor = 1`, the operation is a no-op (image copy).

## Mathematics

Let $I$ be the input image and $n$ = `factor`. For **downsample**, the image is first cropped
to $H' = \lfloor H/n \rfloor \cdot n$, $W' = \lfloor W/n \rfloor \cdot n$, then each output
pixel $(i,j)$ aggregates the source block $B_{i,j} = \{(y,x) : ni \le y < n(i+1),\;
nj \le x < n(j+1)\}$:

$$
O_{\text{average}}(i,j) = \frac{1}{n^2} \sum_{(y,x) \in B_{i,j}} I(y,x), \qquad
O_{\text{sum}}(i,j) = \operatorname{clip}\!\left(\sum_{(y,x) \in B_{i,j}} I(y,x),\; 0,\; 1\right).
$$

Average binning acts as a low-pass filter followed by decimation: if the per-input-pixel noise
is $\sigma$ and uncorrelated, the per-output-pixel noise becomes $\sigma / n$ (factor
$\sqrt{n^2} = n$), at the cost of spatial resolution divided by $n$ — the fundamental
trade-off of binning.

For **upsample**, each source pixel $(y,x)$ is replicated across the output block:

$$
O(ni + k,\; nj + l) = I(y,x), \qquad 0 \le k, l < n,
$$

which is order-0 (nearest-neighbor) interpolation: no new information is created, only the
pixel grid is densified.

## Parameters

- **`factor`** — *int*, default `2`, range `1`–`16`. Integer reduction or enlargement factor,
  applied identically to both axes.
- **`mode`** — *enum*, default `downsample`, choices `downsample` / `upsample`. Direction of
  the operation: shrink via binning or enlarge via replication.
- **`downsample_op`** — *enum*, default `average`, choices `average` / `sum`. Aggregation
  operator when shrinking: `average` for classic radiometric binning (reduces noise, keeps
  the value scale), `sum` to preserve total flux (photometric use), clipped to `[0, 1]`.
  Ignored in `upsample` mode.

## Tips & pitfalls

> **Warning** — in `downsample`, pixels beyond the last integer multiple of `factor` are
> **silently dropped** (no padding). On a 4001×3000 image with `factor=2`, the last column is
> lost. No visual consequence on large images, but worth remembering for precise cropping.

> **Note** — `downsample_op = sum` can push a nonzero sky background past `1.0` once
> multiplied by `factor²` terms; the final clip keeps the `[0, 1]` range but can saturate data
> already close to white. Prefer `average` for purely visual use.

- `upsample` only replicates pixels: for a smooth, interpolated enlargement, use
  [Resample](retina-doc://Resample) instead.
- After a `downsample`, the pixel scale (arcsec/pixel) is multiplied by `factor`: remember to
  correct the astrometry (WCS) if the image must remain scientifically usable.
- `is_maskable = False`: geometry changes, so no blend mask applies — the process always runs
  on the whole image.

## See also

- [Resample](retina-doc://Resample) — real-factor resampling with interpolation.
- [Crop](retina-doc://Crop) — cropping without rescaling.
- [Integration](retina-doc://Integration) — combines multiple frames, sometimes after binning.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — background modeling, often done
  at reduced resolution for speed.

## References

- PixInsight — *IntegerResample* tool reference.
- astropy.nddata — *block_reduce*, block reduction by integer factor.
