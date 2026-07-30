---
id: StarRemoval
category: MaskGeneration
title: Star Removal
brief: Removes stars from an image (starless) via inpainting, an ONNX AI network (StarNet/GraXpert), or an external tool.
keywords: [stars, starless, inpainting, StarNet, GraXpert, mask, ONNX]
related: [StarMask, Inpaint, CloneStamp, SeamlessClone]
icon: star-off
references:
  - "Kniazev, N. — StarNet++ (star removal neural network)."
  - "GraXpert — background extraction & AI star removal tool."
  - "scikit-image — restoration.inpaint_biharmonic."
  - "photutils — DAOStarFinder source detection algorithm."
  - "ONNX Runtime — cross-platform neural network inference."
---

## Summary

`StarRemoval` produces a **starless** version of an image: stars are detected and then erased,
reconstructing the background (sky, nebulosity) in their place. Three interchangeable
**backends** share the same interface: `inpaint` (default, no AI dependency, built on photutils +
scikit-image), `onnx` (a StarNet/GraXpert neural network exported to ONNX, run locally through
onnxruntime), and `external` (delegating to a StarNet++/GraXpert command-line executable). The
result serves either as a final artistic starless image or as an intermediate tool for processing
nebulosity and stars separately before recombining them.

## Use cases

- **Isolate the nebulosity** in a star-dense field to stretch or process it (denoising, contrast
  enhancement) without saturating or deforming the stars.
- **Recombine** stars and starless afterward (via `PixelMath` or `ChannelCombination`) with
  independent control of each layer's contrast — a standard modern post-processing technique.
- **Reduce the apparent size** of background stars in a dense field before mosaicking.
- **Prepare a clean background mask** for `BackgroundExtraction` or `ColorCalibration`, free of
  contamination by star cores.

## How it works

The default `inpaint` backend chains three steps:

1. **Detection**: the luminance (channel mean) is fed to `DAOStarFinder` (photutils) after a
   robust background estimate (`sigma_clipped_stats`); the detection threshold is
   `threshold_sigma` standard deviations above the local median, with a search FWHM of `fwhm`.
2. **Masking**: each detected star produces a disk of radius `radius` (pixels) around its
   centroid; the union of these disks forms the binary mask of regions to reconstruct.
3. **Reconstruction**: `inpaint_biharmonic` (scikit-image) fills the mask by solving a
   biharmonic equation on each channel, relying on the surrounding unmasked pixels.

The `onnx` backend delegates the whole job to a pre-trained neural network (StarNet or GraXpert
exported to `.onnx`). Since these networks expect a fixed input size, the image is split into
`tile_size`-sided tiles with `overlap` overlap, each tile is inferred independently, and the
results are **blended back** with linear feathering to avoid visible seams at tile boundaries.

The `external` backend saves the image to a temporary FITS file, invokes `command` (with
`{input}` and `{output}` substituted), then reloads the result produced by the tool — useful for
driving an already-installed StarNet++/GraXpert without reimplementing its pipeline.

## Mathematics

**Detection (DAOStarFinder).** The local background is estimated with robust sigma-clipped
statistics: median $\tilde b$ and standard deviation $\sigma_b$ of the image after iterative
$3\sigma$ clipping. A candidate pixel is kept as a star peak if its intensity, after background
subtraction, exceeds the threshold:

$$ I(x,y) - \tilde b \;>\; \texttt{threshold\_sigma}\cdot \sigma_b . $$

The algorithm then fits a 2D Gaussian profile of width `fwhm` around each peak to refine its
centroid $(x_c, y_c)$.

**Mask.** For each detected star, every pixel $(x,y)$ such that

$$ (x - x_c)^2 + (y - y_c)^2 \;\le\; \texttt{radius}^2 $$

is flagged for reconstruction. The global mask is the boolean union of these disks.

**Biharmonic inpainting.** Over the masked region $\Omega$, each channel $u$ is extended by
solving the homogeneous biharmonic equation with boundary conditions on $\partial\Omega$ (the
known adjacent pixels):

$$ \nabla^4 u = 0 \quad \text{on } \Omega, \qquad u|_{\partial\Omega} = I|_{\partial\Omega}. $$

This fourth-order PDE produces a **curvature-smooth** extension (continuity of $u$ and its
gradient) rather than plain diffusion, which avoids the "blobby" artifacts of classic harmonic
inpainting on small gaps such as star disks.

**Tile blending (`onnx` backend).** Each tile is weighted by a separable 2D window
$w(i,j) = r(i)\,r(j)$, where $r$ equals $1$ at the center and ramps down linearly over `overlap`
pixels at the edges. The final reconstruction is the weighted average of the overlapping tiles:

$$ I_{\text{out}}(x,y) = \frac{\sum_t w_t(x,y)\, T_t(x,y)}{\sum_t w_t(x,y)} . $$

## Parameters

- **`mode`** — *enum*, default `inpaint`, choices `inpaint` / `onnx` / `external`. Backend used
  for removal: classic reconstruction with no AI dependency, a local ONNX network, or an external
  tool driven as a subprocess.
- **`fwhm`** — *real*, default `3.0`, range `1`–`20`. Expected star full-width-half-maximum (in
  pixels) for detection; tune it to sampling and seeing.
- **`threshold_sigma`** — *real*, default `5.0`, range `1`–`50`. Detection threshold in robust
  standard deviations above background; higher means fewer faint stars detected.
- **`radius`** — *real*, default `5.0`, range `1`–`50`. Radius (in pixels) of the masked disk
  around each detected star, before reconstruction.
- **`model`** — *path*, default empty. Path to the `.onnx` model (exported StarNet or GraXpert),
  required in `onnx` mode.
- **`tile_size`** — *int*, default `256`, range `32`–`2048`. Side length (pixels) of the tiles
  submitted to the ONNX network; must match the model's expected input size.
- **`overlap`** — *int*, default `32`, range `0`–`512`. Overlap between adjacent tiles, in
  pixels, used to blend the seams away.
- **`command`** — *str*, default empty. Shell command executed in `external` mode, with the
  `{input}` and `{output}` tokens replaced by the temporary FITS file paths.

## Tips & pitfalls

> **Warning** — the default `inpaint` backend does not "understand" the image: on a very dense
> star field, masked disks overlap and biharmonic reconstruction can leave flat patches or
> residual halos. For quality closer to specialized networks, prefer `onnx` or `external` with a
> trained StarNet/GraXpert model.

> **Note** — `external` mode runs the supplied command through the shell (`subprocess.run(...,
> shell=True)`): never feed it an untrusted string; `command` must stay under the user's control.

- Increase `radius` slightly beyond a star's visual size to also erase its diffraction spikes, at
  the cost of a larger reconstructed area.
- In `onnx` mode, too small an `overlap` produces visible seams between tiles; 32–64 px is
  usually enough for 256 px tiles.
- Work on a copy: the starless version loses information (the stars) that can only be recovered
  by recombining with the original image or a dedicated `StarMask`.

## See also

- [StarMask](retina-doc://StarMask) — generates the star mask alone, without reconstruction, for
  manual combined processing.
- [Inpaint](retina-doc://Inpaint) — generic inpainting on any region, the basis of the `inpaint`
  backend.
- [CloneStamp](retina-doc://CloneStamp) — manual point-by-point retouching, a precise local
  alternative to automatic removal.
- [SeamlessClone](retina-doc://SeamlessClone) — gradient-blended cloning for larger retouches.

## References

- Kniazev, N. — *StarNet++* (star removal neural network).
- GraXpert — *background extraction & AI star removal tool*.
- scikit-image — *restoration.inpaint_biharmonic*.
- photutils — *DAOStarFinder* source detection algorithm.
- ONNX Runtime — cross-platform neural network inference.
