---
id: ComponentSeparation
category: ColorCalibration
title: Component Separation
brief: Decomposes channels into decorrelated or independent PCA/ICA components, pixel by pixel.
keywords: [PCA, ICA, decorrelation, channels, narrowband, gradient, scikit-learn, whitening]
related: [ChannelExtraction, ChannelCombination, LRGBCombination, GradientCorrection]
icon: arrows-split
references:
  - "scikit-learn — sklearn.decomposition.PCA / FastICA."
  - "Hyvärinen, A., Oja, E. — Independent Component Analysis: Algorithms and Applications (2000)."
  - "Jolliffe, I.T. — Principal Component Analysis (2002)."
---

## Summary

`ComponentSeparation` treats the `C` channels of a color image as a set of mixed signals and
extracts a new basis of `C` components from them, using **Principal Component Analysis (PCA)**
or **Independent Component Analysis (ICA)**. Unlike a per-channel transformation (STF, curves…),
the operator looks at the **cross-channel correlation** pixel by pixel and recombines the
information rather than stretching it channel by channel. It is typically used to isolate a
gradient or a signal common to all layers, or to separate a continuum from a narrow emission line
in narrowband imaging.

## Use cases

- **Isolate a correlated gradient** (light pollution, residual vignetting) present in a similar
  way on R, G and B: the 1st PCA component often captures nearly all of it.
- **Decorrelate an LRGB combination** or a bi/tri-band narrowband image (Hα/OIII/SII) to separate
  the stellar continuum from the line signal specific to each filter.
- **Explore the structure of the signal** before a targeted treatment: the dominant component
  concentrates the common signal/noise, later ones isolate finer residuals (chrominance,
  channel-specific artifacts).
- **Prepare a mask or a combination** from an isolated component rather than a raw channel, when
  the latter mixes several sources of signal.

## How it works

Each pixel `(x, y)` is treated as a **`C`-dimensional vector** (a sample), the whole image forming
a cloud of `H×W` samples in that `C`-dimensional space. The process:

1. **Flattens** the `(H, W, C)` image into an `(N, C)` matrix with `N = H·W`.
2. **Fits a scikit-learn model** on that matrix according to `method`:
   - `pca` — `sklearn.decomposition.PCA(n_components=C, whiten=whiten)`: diagonalizes the
     cross-channel covariance and projects onto its eigen-axes, ordered by decreasing variance.
   - `ica` — `sklearn.decomposition.FastICA(n_components=C, whiten="unit-variance")`: searches for
     a basis that maximizes the **non-Gaussianity** (hence statistical independence) of the
     components, with no imposed variance order.
3. **Reshapes** the resulting `(N, C)` components back into the image's `(H, W, C)` geometry.
4. **Rescales each component independently** to `[0, 1]` (per-band min-max), so the result stays
   displayable and chainable with other processes.

The number of output channels is **unchanged** (`C` components for `C` input channels) — only
their meaning changes: they are no longer R/G/B but axes of variance or independence. The
operator requires **at least 2 channels**; on a single-channel image it returns the data
unchanged. The module imports `sklearn` lazily, only at execution time.

## Mathematics

**PCA.** Let $X \in \mathbb{R}^{N \times C}$ be the matrix of centered pixels (each column with
zero mean). The cross-channel covariance is:

$$ \Sigma = \frac{1}{N-1} X^{\top} X \in \mathbb{R}^{C \times C}. $$

PCA diagonalizes $\Sigma$ into eigenvectors and eigenvalues $\Sigma v_k = \lambda_k v_k$, with
$\lambda_1 \ge \lambda_2 \ge \dots \ge \lambda_C \ge 0$. The $k$-th component is the projection
$c_k = X v_k$, with variance $\lambda_k$: component 1 concentrates the largest share of the
variance common to the channels (typically the correlated signal/gradient), later ones the
orthogonal residuals. With `whiten = True`, each component is further scaled by
$\sqrt{\lambda_k}$ to obtain unit variance — useful when the components go on to feed a
scale-sensitive treatment (e.g. cascaded ICA).

**ICA.** FastICA looks for an unmixing matrix $W$ such that $S = XW$ has **statistically
independent** components, by maximizing a non-Gaussianity proxy (negentropy) rather than variance
alone:

$$ J(w) \approx \big[\, \mathbb{E}\{G(w^{\top}x)\} - \mathbb{E}\{G(\nu)\} \,\big]^2, $$

where $\nu$ is a standard Gaussian and $G$ a non-quadratic function (`logcosh` by default in
scikit-learn). The algorithm iterates by fixed point under a whitening constraint
(`whiten="unit-variance"`), which pre-decorrelates and normalizes the channels before the search
for independence — hence the absence of an imposed variance order among ICA components, unlike
PCA. The approach is justified by the central limit theorem: a mixture of independent sources is
*more* Gaussian than each source taken separately, so maximizing the non-Gaussianity of
$w^\top x$ tends to isolate an original source.

In both cases, the output for band $k$ is finally rescaled:

$$ \hat{c}_k(x,y) = \frac{c_k(x,y) - \min c_k}{\max c_k - \min c_k}, $$

(or $0$ everywhere if $\max c_k = \min c_k$, the degenerate case of a constant component).

## Parameters

- **`method`** — *enum*, default `pca`, choices `pca` / `ica`. Decomposition algorithm: `pca`
  for an orthogonal basis ordered by variance (fast, deterministic), `ica` for a basis that
  maximizes statistical independence (more costly, mildly stochastic via an internally fixed
  `random_state`, but reproducible).
- **`whiten`** — *bool*, default `True`. Whitening applied **only in PCA mode** (ICA always
  whitens internally, regardless of this parameter): normalizes each component to unit variance
  before the `[0,1]` rescaling, which equalizes contrast between components of very different
  variance.

## Tips & pitfalls

> **Warning** — the output components **no longer correspond** to the original R/G/B channels: do
> not naively feed them back into `ChannelCombination` expecting to recover a faithful color
> image. Use this process for **inspection** or to isolate a specific component (e.g. via
> `ChannelExtraction` on the result), not as a neutral step in a colorimetric pipeline.

> **Note** — PCA has no sign or absolute-scale guarantee per component: min-max rescaling can
> visually flip the contrast of a component from one run to the next depending on the sign of the
> eigenvector the implementation happens to return.

- On a well-calibrated classic RGB image, PCA component 1 often looks like a grayscale
  (luminance) version; components 2/3 highlight fine chromatic differences, useful for spotting a
  residual color gradient.
- In narrowband, try `ica` rather than `pca` to look for a continuum/line separation closer to a
  real physical independence of sources; compare both methods, as the result depends heavily on
  how mixed the channels actually are.
- The computation runs internally on `float64` for numerical stability of the decomposition, then
  converts back to `float32` — anticipate the memory cost on very large images.

## See also

- [ChannelExtraction](retina-doc://ChannelExtraction) — isolate a component or channel after
  decomposition.
- [ChannelCombination](retina-doc://ChannelCombination) — recompose a color image from channels
  or components.
- [LRGBCombination](retina-doc://LRGBCombination) — the inverse combination, based on explicit
  luminance rather than statistical axes.
- [GradientCorrection](retina-doc://GradientCorrection) — direct removal of a global gradient, a
  simpler alternative when cross-channel correlation is not exploited.

## References

- scikit-learn — *sklearn.decomposition.PCA* / *FastICA*.
- Hyvärinen, A., Oja, E. — *Independent Component Analysis: Algorithms and Applications* (2000).
- Jolliffe, I.T. — *Principal Component Analysis* (2002).
