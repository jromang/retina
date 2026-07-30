"""DynamicPSF — measures the PSF (FWHM, eccentricity) on the detected stars.

A **measurement** process (read-only, like Statistics): detects stars and fits an
**elliptical** 2D Gaussian on the brightest ones to estimate the mean FWHM and eccentricity.
Used to parameterise deconvolution and to assess optical/tracking quality.

# The fit, and who else uses it

:func:`fit_psf_stars` is the shared building block: this module provides it, and
:class:`~retina.processes.subframe.SubframeSelector` consumes it to measure the quality of
each exposure. Writing two fits would have guaranteed that they diverge — and this is
precisely the quantity on which exposures are ranked.

The model is ``photutils.psf.GaussianPSF``, parameterised directly in **FWHM** per axis plus
an angle, with an integrated flux: nothing to convert, and the flux comes for free. One trap:
photutils **freezes** ``x_fwhm``/``y_fwhm``/``theta`` by default, because its PSF models are
meant first of all for photometry with a known PSF. Leaving them frozen returned exactly the
initial value — a fit that fits nothing, and that no assertion about "it converges" detects.
Hence :func:`_free_shape`.

A constant background (``Const2D``) is fitted at the same time: a 15 px cutout taken inside a
sky background gradient does not have a zero background, and charging it to the PSF inflates
its width.

**Gaussian and Moffat**. Astropy and photutils only ship a **circular** Moffat, which would
return no eccentricity at all — the quantity that weighs twice the FWHM in the default
weighting; the elliptical profile is therefore written here (:func:`_make_moffat`), with the
same parameter names as ``GaussianPSF`` so that everything downstream is common to both.

# From measurement to kernel

:func:`psf_kernel` evaluates either profile on a grid, and :func:`median_psf_image` chains
detection, fitting and the median of the shape parameters to return the **measured** PSF of
the field. This is what ``Deconvolution(psf_mode='measured')`` consumes: we had always been
able to measure the PSF without ever being able to hand it to the deconvolution.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register

#: half-side of the fitting cutout, in pixels. Seven covers three times the FWHM of a typical
#: star — enough to constrain the wings, little enough to avoid the neighbours.
PSF_HALF_WINDOW = 7

#: FWHM → arcseconds conversion: 206265 arcsec/rad, pixel size in µm, focal length in mm.
ARCSEC_PER_RADIAN = 206.265

#: FWHM/σ ratio of a Gaussian: FWHM = 2√(2 ln 2) · σ
FWHM_PER_SIGMA = 2.3548200450309493

#: Minimum height of the fitted model, in robust dispersions of the cutout. Below that, we
#: have not measured a star — we have fitted noise, and obtained the initial setting.
MIN_PEAK_SIGMA = 3.0


#: fittable PSF functions. More profiles exist (Moffat with a fixed β, Lorentzian, variable
#: shape); these two cover the usage — the Gaussian for routine measurement, the Moffat when
#: the wings matter.
PSF_FUNCTIONS = ("gaussian", "moffat")

#: bounds on β. Below 1 the Moffat integral diverges: the flux does not exist. Beyond 10, the
#: profile is indistinguishable from a Gaussian and the fit becomes ill-conditioned.
BETA_RANGE = (1.05, 10.0)


def _free_shape(model):
    """Frees the shape parameters, which photutils freezes for photometry."""
    for name in ("x_fwhm", "y_fwhm", "theta"):
        if name in model.param_names:
            model.fixed[name] = False
    return model


def _make_moffat():
    """**Elliptical** Moffat — astropy and photutils only ship a circular one.

    A circular Moffat would return no eccentricity at all, the quantity that weighs twice the
    FWHM in the default weighting. The model is therefore written here, with the **same
    parameter names** as ``GaussianPSF`` (``flux``, ``x_fwhm``, ``y_fwhm``, ``theta``): all
    the downstream fitting code is then common to both functions.

    Profile ``I(r) = A · (1 + r²)^(−β)`` on the reduced elliptical radius, with the standard
    relation between width and FWHM: ``FWHM = 2·α·√(2^(1/β) − 1)``. The integrated flux is
    ``A·π·αx·αy/(β−1)`` — hence the amplitude, so that ``flux`` really is the total flux.
    """
    from astropy.modeling import Fittable2DModel
    from astropy.modeling import Parameter as ModelParameter

    class EllipticalMoffat(Fittable2DModel):
        flux = ModelParameter(default=1.0)
        x_0 = ModelParameter(default=0.0)
        y_0 = ModelParameter(default=0.0)
        x_fwhm = ModelParameter(default=1.0, min=1e-3)
        y_fwhm = ModelParameter(default=1.0, min=1e-3)
        theta = ModelParameter(default=0.0)
        beta = ModelParameter(default=2.5, min=BETA_RANGE[0], max=BETA_RANGE[1])

        @staticmethod
        def evaluate(x, y, flux, x_0, y_0, x_fwhm, y_fwhm, theta, beta):
            width = 2.0 * np.sqrt(np.power(2.0, 1.0 / beta) - 1.0)
            alpha_x = np.maximum(x_fwhm / width, 1e-9)
            alpha_y = np.maximum(y_fwhm / width, 1e-9)
            cos_t, sin_t = np.cos(theta), np.sin(theta)
            dx, dy = x - x_0, y - y_0
            u = (dx * cos_t + dy * sin_t) / alpha_x
            v = (-dx * sin_t + dy * cos_t) / alpha_y
            amplitude = flux * (beta - 1.0) / (np.pi * alpha_x * alpha_y)
            return amplitude * np.power(1.0 + u * u + v * v, -beta)

    return EllipticalMoffat


def _psf_model(function: str, **values):
    """Instantiates the requested PSF function, shape left free."""
    if function == "moffat":
        values.setdefault("beta", 2.5)
        return _make_moffat()(**values)
    from photutils.psf import GaussianPSF

    return _free_shape(GaussianPSF(**values))


def fit_psf_stars(lum: np.ndarray, xs, ys, *, fwhm_guess: float = 3.0,
                  background: float = 0.0, limit: int = 100,
                  half: int = PSF_HALF_WINDOW,
                  function: str = "gaussian") -> list[dict]:
    """Fits an elliptical PSF on each star; one entry per success.

    ``xs``/``ys`` are approximate centroids (the output of a detector). Stars too close to
    the border to carry a complete cutout are ignored, and so are aberrant fits: a width that
    is negative or larger than the cutout is not a wide star, it is a fit that went off the
    rails, and including it in a median would drag the median without signalling anything.

    ``function`` selects the profile (see :data:`PSF_FUNCTIONS`). Both models carry the same
    parameter names, so that everything following the fit is common to them.

    Each entry carries ``fwhm`` (geometric mean of the two axes), ``eccentricity``, the
    integrated ``flux``, ``theta``, the measured signal and — for a Moffat — ``beta``.
    """
    from astropy.modeling import fitting
    from astropy.modeling.models import Const2D

    height, width = lum.shape
    fitter = fitting.TRFLSQFitter()
    yy, xx = np.mgrid[0:2 * half + 1, 0:2 * half + 1].astype(float)
    results: list[dict] = []
    for x0, y0 in zip(xs, ys, strict=True):
        if len(results) >= limit:
            break
        xi, yi = int(round(float(x0))), int(round(float(y0)))
        if not (half <= xi < width - half and half <= yi < height - half):
            continue
        cutout = lum[yi - half:yi + half + 1, xi - half:xi + half + 1] - background
        model = _psf_model(
            function, flux=float(max(cutout.sum(), 1e-9)), x_0=half, y_0=half,
            x_fwhm=fwhm_guess, y_fwhm=fwhm_guess, theta=0.0,
        ) + Const2D(amplitude=float(np.median(cutout)))
        try:
            fitted = fitter(model, xx, yy, cutout)
        except Exception:
            continue
        fx = abs(float(fitted.x_fwhm_0.value))
        fy = abs(float(fitted.y_fwhm_0.value))
        flux = float(fitted.flux_0.value)
        if not (0.0 < fx < 2 * half and 0.0 < fy < 2 * half) or flux <= 0.0:
            continue
        # A fit on a flat area **converges** — to the initial value, and without saying so:
        # plausible width, positive flux, no warning. We must therefore require that the star
        # stand out from the local noise, otherwise an empty field would return as many
        # "measurements" as there were places we looked at, all equal to the starting
        # setting. We compare the **peak** of the model to the robust dispersion of the
        # cutout. The peak is read off the fitted model, and not computed from the flux: the
        # relation between the two depends on the profile, this one does not.
        sommet = float(fitted[0](fitted.x_0_0.value, fitted.y_0_0.value))
        dispersion = float(np.median(np.abs(cutout - np.median(cutout)))) * 1.4826
        # Zero dispersion = strictly uniform cutout: there is nothing to fit, and comparing
        # to an arbitrary floor would pass numerical noise off as a star.
        if dispersion <= 0.0 or sommet < MIN_PEAK_SIGMA * dispersion:
            continue
        # A fit that runs away to a noise peak at the other end of the cutout has not
        # measured the star it was pointed at — it has invented another one. Detection places
        # the centre to within a pixel; beyond half the cutout, this is no longer a
        # refinement.
        deviation = np.hypot(float(fitted.x_0_0.value) - half, float(fitted.y_0_0.value) - half)
        if deviation > half / 2.0:
            continue
        large, small = max(fx, fy), min(fx, fy)
        signal, count = _elliptical_signal(
            cutout, float(fitted.x_0_0.value), float(fitted.y_0_0.value),
            fx, fy, float(fitted.theta_0.value), float(fitted.amplitude_1.value),
        )
        # An ellipse that covers no pixel of the cutout measures nothing: keeping the entry
        # would distort the mean flux, which divides by that count.
        if count <= 0:
            continue
        results.append({
            "x": float(fitted.x_0_0.value) + xi - half,
            "y": float(fitted.y_0_0.value) + yi - half,
            "fwhm": float(np.sqrt(fx * fy)),
            # The two axes separately, in addition to their geometric mean: this is what is
            # needed to *draw* the fitted ellipse. Reconstructing them from `fwhm` and
            # `eccentricity` would be possible but absurd — they are right here, at hand.
            "fwhm_x": fx,
            "fwhm_y": fy,
            "eccentricity": float(np.sqrt(max(1.0 - (small * small) / (large * large), 0.0))),
            "theta": float(fitted.theta_0.value),
            "flux": flux,
            "signal": signal,
            "signal_count": count,
            **({"beta": float(fitted.beta_0.value)} if function == "moffat" else {}),
        })
    return results


#: below this, an "average PSF" is only the shape of one or two stars, with their noise and
#: their possible companion. Three is the minimum for a median to mean anything at all.
MIN_PSF_SAMPLE = 3

#: maximum half-side of the kernel returned by :func:`median_psf_image`. Beyond that,
#: deconvolution costs more than it brings, and a FWHM that large signals an off-topic image
#: (a nebula taken for a star) rather than a genuine need.
MAX_PSF_RADIUS = 64


def _median_angle(thetas: np.ndarray) -> float:
    """Median of ellipse orientations, which are defined **modulo π**.

    A naive median of angles is wrong as soon as they straddle the cut: two stars at +89° and
    −89° point in almost the same direction, their arithmetic mean points perpendicular to
    it. So we take the median of the components of the **doubled** angle, which closes the
    circle on itself, before coming back.
    """
    if not len(thetas):
        return 0.0
    double = 2.0 * thetas
    return 0.5 * float(np.arctan2(np.median(np.sin(double)), np.median(np.cos(double))))


def psf_kernel(*, function: str = "gaussian", fwhm_x: float, fwhm_y: float | None = None,
               theta: float = 0.0, beta: float = 2.5, size: int | None = None) -> np.ndarray:
    """Normalised PSF kernel (sum 1, odd side), evaluated on a grid.

    The kernel comes from the **same model** as the fit (:func:`_psf_model`): that is what
    guarantees that a measured PSF and a parametric PSF of the same FWHM are the same thing.
    Rewriting the profile here would have produced two Moffats that diverge at the first
    change of convention on α.

    Without ``size``, the side is dimensioned from the FWHM: two FWHM of radius, i.e. ~4.7 σ
    for a Gaussian — enough that the truncation does not show in a deconvolution.
    """
    fx = float(fwhm_x)
    fy = float(fx if fwhm_y is None else fwhm_y)
    if not (fx > 0.0 and fy > 0.0):
        raise ValueError(_t("psf_kernel: strictly positive FWHM expected"))
    radius = int(np.ceil(2.0 * max(fx, fy))) if size is None else int(size) // 2
    radius = int(np.clip(radius, 1, MAX_PSF_RADIUS))

    values: dict[str, float] = {"x_fwhm": fx, "y_fwhm": fy, "theta": float(theta)}
    if function == "moffat":
        values["beta"] = float(np.clip(beta, *BETA_RANGE))
    model = _psf_model(function, flux=1.0, x_0=radius, y_0=radius, **values)
    yy, xx = np.mgrid[0:2 * radius + 1, 0:2 * radius + 1].astype(float)
    kernel = np.asarray(model(xx, yy), dtype=np.float64)
    total = float(kernel.sum())
    if not np.isfinite(total) or total <= 0.0:
        raise ValueError(_t("psf_kernel: zero-sum kernel"))
    return (kernel / total).astype(np.float32)


def median_psf_image(lum: np.ndarray, *, function: str = "gaussian",
                     fwhm_guess: float = 3.0, threshold_sigma: float = 5.0,
                     limit: int = 100, size: int | None = None) -> np.ndarray | None:
    """PSF kernel **measured** on the stars of the field, or ``None`` if there are too few.

    This is the link that was missing between :func:`fit_psf_stars` and deconvolution: we had
    always been able to measure the PSF, without ever being able to hand it over. The stars
    are detected, fitted, then we take the median of their shape parameters and **evaluate
    the model** on a grid — rather than stacking the cutouts, which would bring their noise
    and their neighbours into the kernel.

    ``function`` selects the profile (see :data:`PSF_FUNCTIONS`); the returned kernel is
    normalised to sum 1, has an odd side, and is dimensioned from the measured FWHM if
    ``size`` is not given.
    """
    from astropy.stats import sigma_clipped_stats

    from .stars import detect_sources

    if lum.ndim != 2:
        raise ValueError(_t("median_psf_image expects a 2D luminance image"))
    sources = detect_sources(lum, fwhm_guess, threshold_sigma)
    if sources is None or not len(sources):
        return None
    # Brightest first: on a bounded number of fits, those are the ones whose shape is best
    # constrained.
    sources.sort("flux")
    sources.reverse()
    xcol = "xcentroid" if "xcentroid" in sources.colnames else "x_centroid"
    ycol = "ycentroid" if "ycentroid" in sources.colnames else "y_centroid"
    _, median, _ = sigma_clipped_stats(lum, sigma=3.0)

    stars = fit_psf_stars(lum, list(sources[xcol]), list(sources[ycol]),
                            fwhm_guess=fwhm_guess, background=float(median),
                            limit=int(limit), function=function)
    if len(stars) < MIN_PSF_SAMPLE:
        return None

    beta = (float(np.median([e["beta"] for e in stars]))
            if function == "moffat" else 2.5)
    try:
        return psf_kernel(
            function=function,
            fwhm_x=float(np.median([e["fwhm_x"] for e in stars])),
            fwhm_y=float(np.median([e["fwhm_y"] for e in stars])),
            theta=_median_angle(np.asarray([e["theta"] for e in stars], dtype=float)),
            beta=beta, size=size,
        )
    except ValueError:
        return None


def _elliptical_signal(cutout: np.ndarray, cx: float, cy: float, fwhm_x: float,
                       fwhm_y: float, theta: float, background: float) -> tuple[float, int]:
    """Flux **measured** above the background, over the elliptical region of the PSF.

    Measured rather than integrated analytically, and that is what gives PSFSW its meaning:
    an integrated model would report the same flux whatever the actual quality of the pixels,
    whereas what we want to weigh is what the sensor actually *received*.

    Also returns the number of pixels kept: the **mean** flux per pixel, which PSFSW needs,
    is the quotient of the two.
    """
    height, width = cutout.shape
    ys, xs = np.mgrid[0:height, 0:width]
    dx, dy = xs - cx, ys - cy
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    u = (dx * cos_t + dy * sin_t) / max(SIGNAL_ELLIPSE_FWHM * fwhm_x, 1e-9)
    v = (-dx * sin_t + dy * cos_t) / max(SIGNAL_ELLIPSE_FWHM * fwhm_y, 1e-9)
    inside = (u * u + v * v) <= 1.0
    count = int(inside.sum())
    if not count:
        return 0.0, 0
    return float(np.sum(cutout[inside] - background)), count


# --- signal metrics (PSF Signal Weight, PSF SNR) --------------------------------------
#
# PSFSW and PSFSNR are established subframe-quality metrics; the definitions and their
# normalisation constants are the published ones, and the implementation below is ours, in
# numpy. What differs from any other implementation is everything underneath: star detection,
# fitting, background model. Absolute values are therefore not comparable across tools — the
# ranking of a batch, which is the only use these quantities have, is.
#
# What they add over an ordinary SNR: they weigh the **signal actually collected on the
# stars** against the noise *and* the background. A frame shot through moonlight or high haze
# has a raised background without any more signal — a global SNR may say nothing about it,
# while PSFSW penalises it. They are supplementary quantities, to be enabled knowingly, which
# is why the default weighting formula leaves them at zero.

#: normalisation of N* from the raw MAD. N* is not σ (it is ≈ 1.675 times it): it is a defined
#: quantity, and the PSFSW and PSFSNR constants account for that.
NSTAR_FROM_MAD = 2.48308

#: scale of the background model, in pixels
BACKGROUND_SCALE = 256

#: beyond this, a pixel is no longer background but structure — star, satellite, galaxy
BACKGROUND_CLIP_SIGMA = 3.0

#: semi-axes of the elliptical signal-integration region, in fitted **FWHM**. Expressed that
#: way rather than in σ, the region does not depend on the profile: a Gaussian and a Moffat
#: integrate the same area, so their signals compare. The value is 3 σ for a Gaussian, i.e.
#: ~98.9 % of its flux.
SIGNAL_ELLIPSE_FWHM = 3.0 / FWHM_PER_SIGMA


def local_background_residual(lum: np.ndarray, scale: int = BACKGROUND_SCALE,
                              clip: float = BACKGROUND_CLIP_SIGMA) -> np.ndarray:
    """Background pixels, gradient removed but level preserved — the basis of M* and N*.

    We model the background at **large scale**, subtract that model, then keep only the
    non-significant pixels: what remains is background and noise, without stars. The median
    level of the model is reinjected, so that the median of the result estimates the
    background (M*) and its dispersion the noise (N*) — both quantities come from the same
    array.

    The model is computed from a **decimated** image: a background defined at 256 px has
    nothing to say below that, and computing it at full resolution would cost a hundred times
    more for the same result. The residual, on the other hand, stays at full resolution —
    that is where the noise lives.
    """
    from scipy.ndimage import median_filter
    from skimage.transform import resize

    pas = max(1, scale // 16)
    small = lum[::pas, ::pas]
    # The window must stay **local**: on an image smaller than the requested scale, a median
    # that covers nearly the whole frame no longer models the background, it returns a
    # constant — the gradient then stays in the residual and inflates N* without warning. So
    # we degrade to a finer scale, which is the intended behaviour: a background defined at
    # 256 px makes no sense on a 300 px cutout.
    window = max(3, min(scale // pas, max(3, min(small.shape) // 3)))
    model = median_filter(small, size=window, mode="reflect")
    background = resize(model, lum.shape, order=1, mode="reflect", anti_aliasing=False)

    residual = lum - background
    centre = float(np.median(residual))
    dispersion = 1.4826 * float(np.median(np.abs(residual - centre)))
    if dispersion <= 0.0:
        return np.asarray([], dtype=np.float64)
    kept = np.abs(residual - centre) < clip * dispersion
    if not kept.any():
        return np.asarray([], dtype=np.float64)
    return (residual[kept] + float(np.median(background[kept]))).astype(np.float64)


def m_star(residual: np.ndarray) -> float:
    """M* — robust estimate of the background level."""
    return float(np.median(residual)) if residual.size else 0.0


def n_star(residual: np.ndarray) -> float:
    """N* — robust estimate of the noise, through the MAD variant."""
    if not residual.size:
        return 0.0
    return NSTAR_FROM_MAD * float(np.median(np.abs(residual - np.median(residual))))


def psf_signal_weight(total_flux: float, total_mean_flux: float,
                      background: float, noise: float) -> float:
    """PSF Signal Weight (PSFSW), in its published form.

    ``(5.326e-6 · ΣF · ΣF̄) / (9.0e6 · N* · M*)``, where ``ΣF`` is the sum of the fluxes
    measured on the stars and ``ΣF̄`` the sum of their **mean** per-pixel fluxes.
    """
    if noise <= 0.0 or background <= 0.0:
        return 0.0
    return (5.326e-6 * total_flux * total_mean_flux) / (9.0e6 * noise * background)


def psf_snr(total_flux: float, noise: float) -> float:
    """PSF SNR — ``(1.316e-7 · ΣF²) / (4.987e6 · N*²)``, likewise."""
    if noise <= 0.0:
        return 0.0
    return (1.316e-7 * total_flux * total_flux) / (4.987e6 * noise * noise)


def pixel_scale(pixel_size_um: float, focal_length_mm: float) -> float:
    """Scale in arcsec/pixel, or 0 if either of the two terms is missing.

    ``206.265 × pixel_size(µm) / focal_length(mm)`` — everyone's formula, also known as the
    "camera resolution".
    """
    if pixel_size_um <= 0.0 or focal_length_mm <= 0.0:
        return 0.0
    return ARCSEC_PER_RADIAN * pixel_size_um / focal_length_mm


@register
class DynamicPSF(Process):
    process_id = "DynamicPSF"
    category = "ImageInspection"
    parameters = [
        Parameter("fwhm", "real", 3.0, 1.0, 20.0, label=N_("Detection FWHM")),
        Parameter("threshold_sigma", "real", 5.0, 1.0, 50.0, label=N_("Threshold (σ)")),
        Parameter("max_stars", "int", 50, 1, 500, label=N_("Fitted stars (max)")),
        # Flat list [x0, y0, x1, y1, …] of approximate centroids. When non-empty, it
        # **replaces** detection: that is what makes the "click a star" gesture scriptable,
        # rather than a capability reserved to the interface. `DynamicAlignment` already uses
        # this form.
        Parameter("positions", "floatlist", [], label=N_("Explicit positions")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    @staticmethod
    def _paires(flat) -> tuple[list[float], list[float]]:
        """Splits a flat list into xs/ys. An odd length loses its last number."""
        values = [float(v) for v in (flat or [])]
        return values[0::2], values[1::2]

    def measure(self, image) -> dict:
        from astropy.stats import sigma_clipped_stats

        d = image.data if hasattr(image, "data") else np.asarray(image)
        lum = d.mean(axis=2) if d.shape[2] > 1 else d[:, :, 0]
        _, median, std = sigma_clipped_stats(lum, sigma=3.0)

        xs, ys = self._paires(self.positions)
        if not xs:
            from photutils.detection import DAOStarFinder

            sources = DAOStarFinder(
                fwhm=self.fwhm, threshold=self.threshold_sigma * std
            )(lum - median)
            if sources is None or not len(sources):
                self.result = {"n_stars": 0, "fwhm": None, "eccentricity": None, "stars": []}
                return self.result
            # Brightest first: on a bounded number of fits, those are the ones whose shape is
            # best constrained.
            sources.sort("flux")
            sources.reverse()
            xcol = "xcentroid" if "xcentroid" in sources.colnames else "x_centroid"
            ycol = "ycentroid" if "ycentroid" in sources.colnames else "y_centroid"
            xs, ys = list(sources[xcol]), list(sources[ycol])

        stars = fit_psf_stars(lum, xs, ys,
                                fwhm_guess=float(self.fwhm), background=float(median),
                                limit=max(int(self.max_stars), len(xs)))
        self.result = {
            "n_stars": len(stars),
            "fwhm": float(np.median([e["fwhm"] for e in stars])) if stars else None,
            "eccentricity": (float(np.median([e["eccentricity"] for e in stars]))
                             if stars else None),
            # The per-star detail: without it, the interface can neither draw the fitted
            # ellipses nor list the measurements — it only received three medians.
            "stars": stars,
        }
        return self.result

    def execute_on(self, view) -> bool:  # read-only
        self.measure(view.image)
        return True

    def execute_on_image(self, image):
        self.measure(image)
        return image


@register
class RadialProfileMeasurement(Process):
    """Radial profile + curve of growth of the brightest star (photutils).

    Read-only: locates the brightest peak, samples the radial profile (``RadialProfile``) and
    the flux curve of growth (``CurveOfGrowth``), and derives the FWHM from them. Used for
    collimation / focus checking. Result in ``.result``.
    """

    process_id = "RadialProfileMeasurement"
    category = "ImageInspection"
    parameters = [
        Parameter("max_radius", "int", 15, 3, 200, label=N_("Maximum radius (pixels)")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    def measure(self, image) -> dict:
        from photutils.profiles import CurveOfGrowth, RadialProfile

        d = image.data if hasattr(image, "data") else np.asarray(image)
        lum = d.mean(axis=2) if d.shape[2] > 1 else d[:, :, 0]
        yc, xc = np.unravel_index(int(np.argmax(lum)), lum.shape)
        rmax = int(self.max_radius)
        edges = np.arange(0.0, rmax + 1.0)
        rp = RadialProfile(lum, (float(xc), float(yc)), edges)
        cog = CurveOfGrowth(lum, (float(xc), float(yc)), edges[1:])
        try:
            fwhm = float(rp.gaussian_fwhm)
        except Exception:
            fwhm = None
        self.result = {
            "center": (int(xc), int(yc)),
            "fwhm": fwhm,
            "radius": rp.radius.tolist(),
            "profile": rp.profile.tolist(),
            "curve_of_growth": cog.profile.tolist(),
        }
        return self.result

    def execute_on(self, view) -> bool:  # read-only
        self.measure(view.image)
        return True

    def execute_on_image(self, image):
        self.measure(image)
        return image
