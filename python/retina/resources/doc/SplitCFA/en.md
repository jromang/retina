---
id: SplitCFA
category: Calibration
title: CFA Split (SplitCFA)
brief: "Splits a single-channel CFA (Bayer) mosaic into 4 half-resolution sub-planes stacked as channels, one per filter site."
keywords: [CFA, Bayer, mosaic, demosaicing, decimation, super-pixel, channels]
related: [MergeCFA, Debayer, CosmeticCorrection, NoiseReduction]
icon: grid-dots
references:
  - "PixInsight — SplitCFA / MergeCFA scripts (PixInsight Scripts repository)."
  - "Bayer CFA convention RGGB/BGGR/GRBG/GBRG — see `Debayer`."
---

## Summary

`SplitCFA` takes a **raw, un-demosaiced single-channel image** — the color filter array
mosaic (CFA, typically a Bayer pattern) as delivered by the sensor — and reorganizes it into
**4 half-resolution planes** stacked as channels (`CFA0`..`CFA3`), one per position in the
repeating 2×2 filter block. It is a purely geometric **decimation/repacking** operation, with
no interpolation and no information loss: `MergeCFA` is its exact inverse.

## Use cases

- **Fix hot/cold pixels per photosite** (`CosmeticCorrection`) before demosaicing, so a defect
  is not smeared onto its neighbors by the `Debayer` interpolation.
- **Calibrate or stack each filter site separately** (a "super-pixel" / CFA-drizzle approach) —
  per-plane bias/dark/flat — before recombining with `MergeCFA` and demosaicing.
- **Denoise each raw channel independently** (`NoiseReduction`, `WaveletDenoise`…) without
  letting the noise of one site leak into its neighbors through color interpolation.
- **Analyze per-filter noise or background gradient** on native sensor data, before any color
  reconstruction.

## How it works

`SplitCFA` operates only on **channel 0** of the input image (the raw CFA mosaic is assumed to
be single-channel, captured before any demosaicing).

1. Height and width are truncated to the next-lower even number: a trailing odd row or column,
   if any, is dropped.
2. The plane is split into **four sub-grids** by factor-2 decimation, according to row and
   column parity: (even row, even column), (even, odd), (odd, even), (odd, odd).
3. The four sub-grids, each of size `(H/2, W/2)`, are stacked as a fourth dimension, yielding
   an output of shape `(H/2, W/2, 4)`.

Unlike `Debayer`, `SplitCFA` **does not interpret** the filter pattern (RGGB, BGGR, GRBG,
GBRG): it has no `pattern` parameter. It merely repartitions the grid by parity; it is up to
the user to know which plane (`CFA0`..`CFA3`) corresponds to which color filter, based on the
sensor's actual pattern.

## Mathematics

Let $C(y, x)$ be the input CFA mosaic, $y \in [0, H)$, $x \in [0, W)$. Truncate to even
dimensions $H' = 2\lfloor H/2 \rfloor$, $W' = 2\lfloor W/2 \rfloor$. For
$i \in [0, H'/2)$, $j \in [0, W'/2)$, the four planes are:

$$
P_0(i,j) = C(2i,\,2j), \quad
P_1(i,j) = C(2i,\,2j{+}1), \quad
P_2(i,j) = C(2i{+}1,\,2j), \quad
P_3(i,j) = C(2i{+}1,\,2j{+}1).
$$

The output is the stack $S(i,j,k) = P_k(i,j)$ for $k \in \{0,1,2,3\}$, of shape
$(H'/2, W'/2, 4)$. This mapping is a **bijection** between the truncated pixel grid and the
output cube; it is losslessly reversible, exactly inverted by `MergeCFA`:

$$ C(2i+a,\; 2j+b) = S(i, j,\; 2a+b), \qquad a, b \in \{0,1\}. $$

No averaging, interpolation, or filtering is involved: each output sample is a relocated input
pixel, not a combination of pixels.

## Parameters

This process has **no parameters**. The split always follows the even/odd order of rows and
columns; there is no CFA pattern choice (unlike `Debayer`), because the operation depends only
on parity, not on the color of the filters.

## Tips & pitfalls

> **Warning** — `SplitCFA` assumes a **single-channel** input (a raw mosaic). Applied to an
> already-color image (RGB, from a `Debayer` step or a standard file), it silently uses only
> channel 0 (red) without raising an error: the result is then physically meaningless.

> **Note** — the color identity of planes `CFA0`..`CFA3` depends on the sensor's actual Bayer
> pattern **and** on any parity shift introduced by an earlier crop (a crop offset by one odd
> pixel swaps even and odd rows/columns). Always check the correspondence with the pattern
> declared in `Debayer` before interpreting the planes as R/G/G/B.

- Always pair `SplitCFA` with `MergeCFA` around a per-photosite step: the recombined result
  must be bit-exact to the original if no processing was applied in between.
- The two "green" planes (`CFA1`/`CFA2` under RGGB) can differ slightly in gain: processing
  them separately and recombining preserves that information instead of averaging it away.

## See also

- [MergeCFA](retina-doc://MergeCFA) — recomposes the full-resolution mosaic (exact inverse).
- [Debayer](retina-doc://Debayer) — full demosaicing with CFA pattern interpretation.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — defect correction, ideally applied
  per photosite.
- [NoiseReduction](retina-doc://NoiseReduction) — denoising, applicable channel by channel
  after splitting.

## References

- PixInsight — *SplitCFA* / *MergeCFA* scripts (PixInsight Scripts repository).
- Bayer CFA convention RGGB/BGGR/GRBG/GBRG — see `Debayer`.
