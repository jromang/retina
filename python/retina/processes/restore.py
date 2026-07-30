"""Restoration: deconvolution, noise reduction, morphology, unsharp.

Thin wrappers over scikit-image / scipy.ndimage. Lazy imports (extra ``[astro]``).
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register
from .psf import BETA_RANGE, PSF_FUNCTIONS


def _gaussian_psf(sigma: float) -> np.ndarray:
    r = max(1, int(np.ceil(3 * sigma)))
    ax = np.arange(-r, r + 1, dtype=np.float64)
    g = np.exp(-(ax**2) / (2 * sigma**2))
    k = np.outer(g, g)
    return k / k.sum()


def _luminance(data: np.ndarray) -> np.ndarray:
    """Luminance plane of an ``(H, W, C)`` array — mean of the channels, as everywhere here."""
    arr = np.asarray(data)
    if arr.ndim == 2:
        return arr.astype(np.float64, copy=False)
    plan = arr.mean(axis=2) if arr.shape[2] > 1 else arr[:, :, 0]
    return plan.astype(np.float64, copy=False)


#: maximum number of progress reports over one run. A deconvolution of 500 iterations over
#: three channels would make 1500 notifications; the cancellation point, for its part, stays
#: at every iteration — it is local and costs nothing.
_MAX_RAPPORTS = 50


@register
class Deconvolution(Process):
    """Regularized Richardson-Lucy, with a parametric, measured or external PSF.

    Three things distinguish this process from the original version, which was nothing but a
    call to ``skimage`` with a synthetic Gaussian:

    - **the PSF can be the image's own**. ``psf_mode='measured'`` fits the stars of the field
      (:func:`~retina.processes.psf.median_psf_image`, the fitter shared with ``DynamicPSF``
      and ``SubframeSelector``) and deconvolves by the shape actually measured, eccentricity
      included. ``'external'`` takes a view as the kernel.
    - **the regularization** (multiscale thresholding of the iterate) makes long
      deconvolutions usable: without it, iterating further ends up amplifying nothing but the
      background noise. See :mod:`retina.backend.deconvolve` for the measurement.
    - **the deringing** attenuates the rings where they are born — in the neighborhood of the
      strong gradients for the global version, on the stars themselves for the local support.
    """

    process_id = "Deconvolution"
    category = "Deconvolution"
    parameters = [
        Parameter("psf_mode", "enum", "parametric",
                  choices=("parametric", "measured", "external"), label=N_("PSF source")),
        Parameter("psf_function", "enum", "gaussian", choices=PSF_FUNCTIONS,
                  label=N_("PSF profile")),
        # Kept identical (id, type, default, bounds): a process icon saved before this change
        # replays without migration, and yields the same result.
        Parameter("psf_sigma", "real", 2.0, 0.1, 20.0, label=N_("PSF sigma")),
        Parameter("psf_beta", "real", 2.5, BETA_RANGE[0], BETA_RANGE[1],
                  label=N_("Moffat beta")),
        Parameter("psf_view", "str", "", label=N_("PSF image (view identifier)")),
        Parameter("star_threshold", "real", 5.0, 1.0, 50.0,
                  label=N_("Star detection threshold (sigma)")),
        Parameter("iterations", "int", 20, 1, 500, label=N_("Iterations")),
        Parameter("regularization", "real", 0.0, 0.0, 10.0,
                  label=N_("Regularization (sigma)")),
        Parameter("dering_dark", "real", 0.0, 0.0, 1.0, label=N_("Dark ringing suppression")),
        Parameter("dering_bright", "real", 0.0, 0.0, 1.0,
                  label=N_("Bright ringing suppression")),
        Parameter("star_protection", "real", 0.0, 0.0, 1.0, label=N_("Star protection")),
        Parameter("luminance_only", "bool", False, label=N_("Luminance only")),
    ]

    # --- PSF ------------------------------------------------------------------
    def _psf(self, data: np.ndarray) -> np.ndarray:
        if self.psf_mode == "external":
            return self._psf_externe()
        if self.psf_mode == "measured":
            from .psf import FWHM_PER_SIGMA, median_psf_image

            kernel = median_psf_image(
                _luminance(data), function=self.psf_function,
                fwhm_guess=float(self.psf_sigma) * FWHM_PER_SIGMA,
                threshold_sigma=float(self.star_threshold),
            )
            if kernel is None:
                raise ValueError(
                    _t("Deconvolution(psf_mode='measured'): not enough fittable stars "
                       "in this field. Lower star_threshold, or switch to "
                       "psf_mode='parametric'.")
                )
            return kernel
        if self.psf_function == "moffat":
            from .psf import FWHM_PER_SIGMA, psf_kernel

            return psf_kernel(function="moffat",
                              fwhm_x=float(self.psf_sigma) * FWHM_PER_SIGMA,
                              beta=float(self.psf_beta))
        return _gaussian_psf(self.psf_sigma)

    def _psf_externe(self) -> np.ndarray:
        from ..process import context

        if not self.psf_view:
            raise ValueError(_t("Deconvolution(psf_mode='external'): psf_view not set"))
        arr = context.resolve_image_full(self.psf_view)
        if arr is None:
            raise ValueError(
                _t("Deconvolution: PSF view not found ({view!r})").format(view=self.psf_view))
        kernel = _luminance(arr) if arr.ndim == 3 else np.asarray(arr, dtype=np.float64)
        # A PSF thumbnail carries the sky background it was cut out of; leaving it in would
        # make a kernel with a plateau, which blurs instead of restoring.
        kernel = kernel - float(np.median(kernel))
        kernel = np.clip(kernel, 0.0, None)
        total = float(kernel.sum())
        if total <= 0.0:
            raise ValueError(
                _t("Deconvolution: view {view!r} carries no PSF").format(view=self.psf_view))
        return (kernel / total).astype(np.float32)

    # --- execution ------------------------------------------------------------
    def _deconvoluer(self, plan: np.ndarray, psf: np.ndarray, base: float,
                     portee: float) -> np.ndarray:
        """One deconvolved channel — **here, and nowhere else, is where we move up to the GPU**.

        Bracketing the single call to the loop lets everything downstream
        (`output[:, :, c] = …`, the luminance handling, the deringing) receive numpy and
        **change nothing**. Three PCIe round trips per image, a few tens of milliseconds,
        against a loop that costs thousands of them: the arithmetic is quickly done. The
        deringing knowingly stays on the CPU — those are cheap single passes, and porting them
        would multiply the bug surface for an invisible gain.
        """
        from ..backend.deconvolve import richardson_lucy
        from ..backend.xp import free_gpu_memory, is_oom, to_device, to_numpy

        tours = max(int(self.iterations), 1)
        pas = max(1, tours // _MAX_RAPPORTS)

        def tour(i: int) -> None:
            # Cancellation at every iteration, a report once every `pas`: the checkpoint is
            # local and free, whereas the notification crosses the network. Neither of the two
            # touches the device, so neither synchronizes.
            self._checkpoint()
            if i % pas == 0 or i == tours:
                self._progress(base + portee * i / tours,
                               _t("Deconvolution — iteration {n}/{total}").format(
                                   n=i, total=tours))

        entry = np.clip(plan, 0.0, None)
        uploaded = to_device(entry)
        if uploaded is entry:  # nothing more to do: the original CPU path
            return richardson_lucy(entry, psf, tours,
                                   regularization=float(self.regularization),
                                   on_iteration=tour)
        try:
            from ..backend.xp import get_array_module

            kernel = get_array_module(uploaded).asarray(psf)
            return to_numpy(richardson_lucy(uploaded, kernel, tours,
                                            regularization=float(self.regularization),
                                            on_iteration=tour))
        except Exception as exc:
            if not is_oom(exc):
                raise
            # Not enough GPU memory: we give its blocks back to the driver and redo the same
            # computation on the CPU. Slow, but a slow result beats an error.
            free_gpu_memory()
            return richardson_lucy(entry, psf, tours,
                                   regularization=float(self.regularization),
                                   on_iteration=tour)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        psf = self._psf(data)
        if self.luminance_only and data.shape[2] >= 3:
            output = self._apply_luminance(data, psf)
        else:
            channels = data.shape[2]
            output = np.empty_like(data)
            for c in range(channels):
                self._progress(c / channels, _t("Deconvolution — channel {n}/{total}").format(
                    n=c + 1, total=channels))
                output[:, :, c] = self._deconvoluer(
                    data[:, :, c], psf, c / channels, 1.0 / channels)
        output = self._deringer(data, output)
        self._progress(1.0, _t("Deconvolution"))
        # No clipping at white: Richardson-Lucy *concentrates* the flux, and cutting the core
        # of the stars back to 1.0 would destroy their photometry. The floor at zero, for its
        # part, is already laid down by the algorithm.
        return output.astype(np.float32)

    def _apply_luminance(self, data: np.ndarray, psf: np.ndarray) -> np.ndarray:
        """Deconvolves the luminance alone and reapplies the ratio to the three channels.

        Three times less work, and above all no chromatic drift: deconvolving the channels
        separately makes the red and the blue converge at different speeds, which colors the
        edges of the stars.
        """
        lum = _luminance(data)
        self._progress(0.0, _t("Deconvolution — channel {n}/{total}").format(n=1, total=1))
        restauree = self._deconvoluer(lum, psf, 0.0, 1.0)
        report = restauree / np.maximum(lum, 1e-6)
        return data * report[:, :, None]

    # --- deringing ------------------------------------------------------------
    def _deringer(self, original: np.ndarray, restaure: np.ndarray) -> np.ndarray:
        sombre, clair = float(self.dering_dark), float(self.dering_bright)
        protection = float(self.star_protection)
        if sombre <= 0.0 and clair <= 0.0 and protection <= 0.0:
            return restaure

        from scipy.ndimage import gaussian_filter, gaussian_gradient_magnitude

        output = restaure
        if sombre > 0.0 or clair > 0.0:
            # The rings are born in the neighborhood of the strong transitions, not
            # uniformly: weighting by the gradient of the input concentrates the attenuation
            # there, instead of killing off the sharpness gain over the whole image.
            lum = _luminance(original)
            grad = gaussian_gradient_magnitude(lum, sigma=max(float(self.psf_sigma), 0.5))
            top = float(np.percentile(grad, 99.0))
            weights = np.clip(grad / top, 0.0, 1.0) if top > 0.0 else np.zeros_like(grad)
            residual = output - original
            force = np.where(residual < 0.0, sombre, clair) * weights[:, :, None]
            output = original + residual * (1.0 - force)

        if protection > 0.0:
            mask = self._star_mask(original)
            if mask is not None:
                doux = gaussian_filter(mask, sigma=max(float(self.psf_sigma), 0.5))
                melange = np.clip(doux, 0.0, 1.0)[:, :, None] * protection
                output = output * (1.0 - melange) + original * melange
        return output

    def _star_mask(self, data: np.ndarray) -> np.ndarray | None:
        """Local support of the deringing: disks proportional to the PSF, not fixed ones."""
        from .stars import detect_sources, star_mask

        lum = _luminance(data)
        try:
            sources = detect_sources(lum, max(float(self.psf_sigma), 1.0),
                                     float(self.star_threshold))
        except Exception:
            return None
        if sources is None or not len(sources):
            return None
        radius = max(2.0, 2.0 * float(self.psf_sigma))
        return star_mask(lum.shape, sources, radius).astype(np.float32)


@register
class NoiseReduction(Process):
    process_id = "NoiseReduction"
    category = "NoiseReduction"
    parameters = [
        Parameter("method", "enum", "tv", choices=("tv", "wavelet", "bilateral"),
                  label=N_("Method")),
        Parameter("strength", "real", 0.1, 0.0, 2.0, label=N_("Strength")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.restoration import denoise_bilateral, denoise_wavelet

        if self.method == "tv":
            return self._tv(data)
        if self.method == "wavelet":
            try:
                return denoise_wavelet(data, channel_axis=-1, rescale_sigma=True).astype(np.float32)
            except ImportError as exc:  # denoise_wavelet imports PyWavelets lazily
                raise ImportError(
                    _t("NoiseReduction(method='wavelet') requires PyWavelets — "
                       "install the astro extra (pip install 'retina[astro]') or "
                       "'pip install PyWavelets'.")
                ) from exc
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            out[:, :, c] = denoise_bilateral(
                data[:, :, c], sigma_color=self.strength, sigma_spatial=3
            )
        return out.astype(np.float32)

    def _tv(self, data: np.ndarray) -> np.ndarray:
        """Total variation — our own xp implementation, on GPU when it is worth it.

        The same code on both sides (cf. :mod:`retina.backend.denoise`), hence nothing to
        compare between two versions: the result on the host is bit for bit the one of
        skimage, and the parity test holds it.
        """
        from ..backend.denoise import tv_chambolle
        from ..backend.xp import free_gpu_memory, is_oom, to_device, to_numpy

        uploaded = to_device(data)
        if uploaded is data:
            return tv_chambolle(data, self.strength, channel_axis=-1).astype(np.float32)
        try:
            return to_numpy(
                tv_chambolle(uploaded, self.strength, channel_axis=-1)
            ).astype(np.float32)
        except Exception as exc:
            if not is_oom(exc):
                raise
            free_gpu_memory()
            return tv_chambolle(data, self.strength, channel_axis=-1).astype(np.float32)


@register
class MorphologicalTransformation(Process):
    process_id = "MorphologicalTransformation"
    category = "Morphology"
    parameters = [
        Parameter("operation", "enum", "opening",
                  choices=("erosion", "dilation", "opening", "closing",
                           "white_tophat", "black_tophat", "gradient"), label=N_("Operation")),
        Parameter("size", "int", 3, 1, 51, label=N_("Size")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from scipy import ndimage

        fn = {
            "erosion": ndimage.grey_erosion,
            "dilation": ndimage.grey_dilation,
            "opening": ndimage.grey_opening,
            "closing": ndimage.grey_closing,
            "white_tophat": ndimage.white_tophat,   # small bright structures (stars)
            "black_tophat": ndimage.black_tophat,    # small dark structures (defects)
            "gradient": ndimage.morphological_gradient,  # edges = dilation − erosion
        }[self.operation]
        n = int(self.size)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            out[:, :, c] = fn(data[:, :, c], size=(n, n))
        return out.astype(np.float32)


@register
class UnsharpMask(Process):
    process_id = "UnsharpMask"
    category = "Convolution"
    parameters = [
        Parameter("radius", "real", 2.0, 0.1, 50.0, label=N_("Radius")),
        Parameter("amount", "real", 1.0, 0.0, 10.0, label=N_("Amount")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.filters import unsharp_mask

        out = unsharp_mask(data, radius=self.radius, amount=self.amount, channel_axis=-1)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class RestorationFilter(Process):
    """Deconvolution by Wiener filter (linear restoration, Gaussian PSF).

    Direct (non-iterative) alternative to ``Deconvolution`` (Richardson-Lucy): faster, robust
    to noise through the ``balance`` parameter. scikit-image ``restoration.wiener``.
    """

    process_id = "RestorationFilter"
    category = "Deconvolution"
    parameters = [
        Parameter("psf_sigma", "real", 2.0, 0.1, 20.0, label=N_("PSF sigma")),
        Parameter("balance", "real", 0.1, 1e-4, 10.0, label=N_("Balance (regularization)")),
        Parameter("mode", "enum", "wiener",
                  choices=("wiener", "unsupervised"), label=N_("Mode")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.restoration import unsupervised_wiener, wiener

        psf = _gaussian_psf(self.psf_sigma)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            ch = np.clip(data[:, :, c], 0.0, 1.0)
            if self.mode == "unsupervised":
                # regularization estimated automatically (Bayesian): no manual tuning
                restored, _ = unsupervised_wiener(ch, psf, clip=True)
                out[:, :, c] = restored
            else:
                out[:, :, c] = wiener(ch, psf, balance=float(self.balance), clip=True)
        return np.clip(out, 0.0, 1.0).astype(np.float32)
