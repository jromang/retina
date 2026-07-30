"""Richardson-Lucy — the deconvolution loop, written here.

`skimage.restoration.richardson_lucy` did the job, but as a black box: it does not expose its
current iterate. Progress and cancellation could therefore be no finer than one channel,
regularization had nowhere to insert itself, and the ``xp`` dispatch could not apply.
Rewriting the loop unblocks all three at once.

**Convolutions by FFT, with the PSF transforms computed once.** RL applies two convolutions
per iteration, always with the same kernel and its flipped counterpart: preparing them outside
the loop is the only real speed gain over the reference implementation, which redoes them on
every pass.

**Borders handled, in two stages.** scipy's zero-border convolution makes the algorithm believe
the sky stops at the frame, and the resulting dark rim propagates inward with every iteration.
So the image is extended by reflection, cropped back at the end, *and* the correction is
divided by what the flipped kernel actually sees at that spot (``h̃ ⊛ 1``). The second part is
the one that counts: the margin alone still left a 5% dip in the corners after thirty
iterations. Since this normalization equals exactly 1 as soon as one is more than a PSF radius
from the border, it touches nothing else — in the heart of the image the result remains that of
the reference implementation, to within 1e-12.

# The regularization, and why this one

The regularizer chosen is a **multiscale thresholding of the iterate**: on every pass, the
à-trous transform separates the fine layers of the estimate, and whatever does not exceed ``k``
robust dispersions in them is zeroed. It was chosen here by measurement rather than on
principle. Two more obvious candidates were tried and **rejected**:

- **total variation** (Dey 2006) and White's **damping** (1994) do reduce the noise, but both
  are *dominated by the simple fact of iterating less*: at equal background noise, bare RL
  stopped earlier restores more stellar flux. A regularizer that only slows convergence does
  not regularize, it stalls.
- TV has, on top of that, a defect of principle here: it assumes an image made of flat areas,
  when a star is exactly the opposite — its curvature is maximal, so it is the first thing TV
  smooths.

Multiscale thresholding, by contrast, is **scale-selective**: it removes fine noise without
touching fine *significant* structures, stars among them. Measured on a synthetic field with
ground truth (point stars + extended galaxies, noise σ=0.003), at 600 iterations:

=====================  ==========  ================  ============
variant                RMS/truth   background noise  stellar flux
=====================  ==========  ================  ============
bare RL, 30 it.           0.02581           0.00254         0.751
bare RL, 600 it.          0.02598           0.00940         1.041
regularized, 600 it.      0.02313           0.00102         0.768
=====================  ==========  ================  ============

Bare RL **degrades** as it iterates: its background noise is multiplied by 3.7 and its stellar
flux exceeds the truth (1.04 — it fabricates signal). The regularized one keeps the background
stable and goes on improving. That is what makes long deconvolutions usable.

A laboratory figure, however, and it must be said: these measurements bear on **white** noise,
whose fine layer contains nothing else. On a real image, that layer also carries structure —
so the thresholding finds less to remove there, and the gain observed on
``data/real_field.fits`` falls to 17% at 150 iterations. The regularizer does not excuse
reducing the noise before deconvolving; it only prevents manufacturing more.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..i18n import translate as _t
from .xp import fft_for, get_array_module, ndimage_for

#: denominator guard: under a null convolution, the observed/reprojected ratio diverges. The
#: floor is numerical, not physical — it never bites on positive data.
_EPS = 1e-12

#: B3-spline kernel of the à trous transform (Starck), dilated from one scale to the next.
_B3 = (1.0 / 16.0, 4.0 / 16.0, 6.0 / 16.0, 4.0 / 16.0, 1.0 / 16.0)

#: subsampling step for estimating a layer's dispersion. One pixel in sixteen is far more than
#: enough to estimate a standard deviation, and the median is the regularizer's dominant cost —
#: computing it over the whole array on every iteration would cost more than the deconvolution
#: itself.
_SIGMA_STRIDE = 4


def _next_fast_len(n: int, module=None) -> int:
    """Next fast size for the given module's FFT.

    ``scipy.fft`` and ``cupyx.scipy.fft`` know how to answer for *their* implementation — cuFFT
    is just as fast on 7, which the home-grown version below ignores. So they are asked when
    they are there, and we fall back on 5-smooth otherwise.
    """
    if module is not None:
        next_item = getattr(module, "next_fast_len", None)
        if next_item is not None:
            try:
                return int(next_item(int(n)))
            except Exception:
                pass
    while True:
        rest = n
        for factor in (2, 3, 5):
            while rest % factor == 0:
                rest //= factor
        if rest == 1:
            return n
        n += 1


def _atrous_smooth(xp, ndimage, a, scale: int):
    """B3-spline "à trous" smoothing: kernel dilated by 2^(scale−1), separable."""
    pas = 1 << (scale - 1)
    kernel = xp.zeros(4 * pas + 1, dtype=a.dtype)
    kernel[::pas] = xp.asarray(_B3, dtype=a.dtype)
    lisse = ndimage.convolve1d(a, kernel, axis=0, mode="reflect")
    return ndimage.convolve1d(lisse, kernel, axis=1, mode="reflect")


def _robust_sigma(xp, layer):
    """Robust dispersion (MAD × 1.4826) of a layer, estimated on a sample.

    Returns a **scalar of the module**, never a ``float``: on GPU, extracting the value would
    force a synchronization, and there would be one per layer **and per iteration** — enough
    to cancel the entire gain of the port. Comparing it further down therefore also happens on
    the device.
    """
    ech = layer[::_SIGMA_STRIDE, ::_SIGMA_STRIDE]
    centre = xp.median(ech)
    return 1.4826 * xp.median(xp.abs(ech - centre))


def _denoise_scales(xp, ndimage, estimated, threshold: float, layers: int):
    """Hard thresholding of the fine layers of the estimate — the regularizer.

    The à-trous decomposition ``c₀ → c₁ … cₙ`` with ``wᵢ = cᵢ₋₁ − cᵢ``, thresholding of each
    ``wᵢ`` at ``threshold`` robust dispersions, then reconstruction ``cₙ + Σwᵢ``. The
    thresholding is **hard**: a significant coefficient passes through intact. Soft
    thresholding would pull them all toward zero, which would bite into the amplitude of the
    stars — precisely what we are trying to restore.
    """
    current = estimated
    details = []
    for level in range(1, layers + 1):
        lisse = _atrous_smooth(xp, ndimage, current, level)
        detail = current - lisse
        sigma = _robust_sigma(xp, detail)
        # The original ``if sigma > 0`` guard is numerically redundant — at zero sigma the
        # condition ``|detail| < 0`` is false everywhere and the ``where`` returns ``detail``
        # intact — but it cost one synchronization per layer and per iteration. Removing it is
        # what makes the regularized loop fully asynchronous on GPU.
        detail = xp.where(xp.abs(detail) < threshold * sigma, 0.0, detail)
        details.append(detail)
        current = lisse
    for detail in details:
        current = current + detail
    return current


def _centred(xp, psf):
    """Bring the PSF back to odd sides — an even kernel has no central pixel."""
    ph, pw = psf.shape
    if ph % 2 and pw % 2:
        return psf
    out = xp.zeros((ph + (ph + 1) % 2, pw + (pw + 1) % 2), dtype=psf.dtype)
    out[:ph, :pw] = psf
    return out


def richardson_lucy(channel, psf, iterations: int, *, regularization: float = 0.0,
                    regularization_layers: int = 1,
                    on_iteration: Callable[[int], None] | None = None):
    """Deconvolve a 2D image by Richardson-Lucy, with optional multiscale regularization.

    ``channel`` and ``psf`` are 2D arrays of the same module (numpy or CuPy — the dispatch
    follows the input's type, see :mod:`retina.backend.xp`). The PSF is normalized to sum 1:
    the algorithm then conserves flux.

    ``regularization`` is the significance threshold of the fine layers, in robust dispersions;
    0 gives bare RL, 3 is a working value. ``on_iteration`` is called after each pass with the
    iteration number (starting at 1) — that is how the process reports its progress, and how
    cancellation propagates (the function need only raise).

    The starting estimate is a uniform half level, like the reference implementation: the
    choice is not indifferent (starting from the observation converges faster) but changing it
    would move the result of every deconvolution already performed.
    """
    xp = get_array_module(channel, psf)
    img = xp.asarray(channel)
    if img.ndim != 2:
        raise ValueError(_t("richardson_lucy expects a 2D image"))
    dtype = img.dtype if (img.dtype.kind == "f" and img.dtype.itemsize >= 4) else np.float32
    img = img.astype(dtype, copy=False)

    kernel = xp.asarray(psf, dtype=dtype)
    if kernel.ndim != 2:
        raise ValueError(_t("richardson_lucy expects a 2D PSF"))
    kernel = _centred(xp, kernel)
    somme = float(kernel.sum())
    if somme <= 0.0:
        raise ValueError(_t("PSF with null or negative sum"))
    kernel = kernel / somme

    height, width = img.shape
    ph, pw = kernel.shape
    # Reflection margin: one PSF width on each side, never exceeding what `reflect` can
    # produce on a narrow image.
    my = min(ph, max(height - 1, 0))
    mx = min(pw, max(width - 1, 0))
    obs = xp.pad(img, ((my, my), (mx, mx)), mode="reflect") if (my or mx) else img
    # RL assumes counts: a negative value (an over-subtracted background) would yield a
    # negative ratio, hence a negative estimate from the very first pass.
    obs = xp.maximum(obs, 0.0)

    shape = obs.shape
    # `cupyx.scipy.fft` caches its cuFFT plans by shape: since all our transforms share
    # `fforme`, the plan is built once and reused on every pass. On the CPU side, `scipy.fft`
    # is slightly faster than `numpy.fft` — the port benefits both.
    mod_fft = fft_for(obs)
    fforme = (_next_fast_len(shape[0] + ph - 1, mod_fft),
              _next_fast_len(shape[1] + pw - 1, mod_fft))
    h_fft = mod_fft.rfft2(kernel, s=fforme)
    hm_fft = mod_fft.rfft2(kernel[::-1, ::-1], s=fforme)
    dy, dx = ph // 2, pw // 2

    def convoluer(a, noyau_fft):
        full = mod_fft.irfft2(mod_fft.rfft2(a, s=fforme) * noyau_fft, s=fforme)
        return full[dy:dy + shape[0], dx:dx + shape[1]]

    # Right at the frame, the flipped kernel sees only part of its neighborhood: the
    # correction there is mechanically too weak, and the shortfall digs a dark rim that
    # propagates inward on every pass. So we divide by what the kernel really "sees". Inside,
    # this normalization equals exactly 1 (the PSF sums to 1): it touches only the borders, and
    # equality with the reference implementation in the heart of the image is preserved.
    normalisation = xp.maximum(convoluer(xp.ones(shape, dtype=dtype), hm_fft), _EPS)

    threshold = float(regularization)
    layers = max(1, int(regularization_layers))
    ndimage = ndimage_for(obs) if threshold > 0.0 else None

    estimated = xp.full(shape, 0.5, dtype=dtype)
    for tour in range(int(iterations)):
        reprojetee = convoluer(estimated, h_fft)
        report = obs / xp.maximum(reprojetee, _EPS)
        estimated = estimated * convoluer(report, hm_fft) / normalisation
        if threshold > 0.0:
            estimated = _denoise_scales(xp, ndimage, estimated, threshold, layers)
        # In exact arithmetic RL preserves positivity; the FFT, though, leaves residuals on
        # the order of 1e-16 lying around, enough to make the next pass diverge.
        estimated = xp.maximum(estimated, 0.0)
        if on_iteration is not None:
            on_iteration(tour + 1)

    return estimated[my:my + height, mx:mx + width]
