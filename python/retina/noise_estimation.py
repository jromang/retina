"""Image noise estimation — k-sigma and multiresolution support.

The repository could only measure noise through a global `mad_std`, in `SubframeSelector`.
That is not a noise estimator: on an image carrying stars, a nebula and a gradient, the MAD
mostly measures the **structure**. The question to answer is "what is the dispersion of the
pixels that contain *only* noise", and it calls for telling the two apart first.

# The two methods, and why two are needed

**k-sigma** works on the first layer of the starlet transform — the one where noise
dominates — and iteratively clips there at ``k`` dispersions until convergence. Simple,
robust, and it always returns something.

**MRS** (Starck & Murtagh 1998) goes further: it builds the *multiresolution support*, the
map of significant pixels at **all** scales, and estimates the noise only on what is left. On
a dense field, where the first layer is still full of stars, it is markedly more accurate. It
may, on the other hand, fail to converge — too few free pixels — and one then falls back on
k-sigma, as the reference implementations do.

# The factor one forgets

The wavelet coefficients of a Gaussian noise are **not** of the same dispersion as the noise:
the B3-spline convolution attenuates them. The factor is known and tabulated
(:data:`STARLET_SIGMA`); omitting it underestimates the noise by 11% at the first scale,
which shows up in no test comparing two images to each other.
"""

from __future__ import annotations

import numpy as np

from .i18n import translate as _t

#: dispersion of the starlet coefficients of a **unit** Gaussian noise, by scale (Starck &
#: Murtagh). A noise σ gives coefficients of dispersion σ·c_j at scale j.
STARLET_SIGMA = (0.8907, 0.2007, 0.0856, 0.0413, 0.0205, 0.0103, 0.0052)

#: minimum fraction of free pixels for an MRS estimate to mean anything. Half a percent of a
#: one-megapixel image is still five thousand pixels, amply enough to estimate a dispersion;
#: below that, there is no background left at all and the result would be that of the
#: structure.
MRS_MIN_FRACTION = 0.005

#: number of scales entering the multiresolution support. **Two**, and that is a measurement
#: and not a setting: beyond it, a dense field is significant *everywhere* at large scales —
#: which is true, but unrelated to noise at the pixel scale — and the estimate gives up.
#: Below it (a single scale), the wings of the stars are still counted as background and the
#: noise comes out 8% too high on two thousand stars, 55% on eight thousand.
MRS_SUPPORT_SCALES = 2


def _sigma_starlet(scale: int) -> float:
    return STARLET_SIGMA[min(scale, len(STARLET_SIGMA) - 1)]


def _truncation_correction(k: float) -> float:
    """What clipping takes away from the dispersion, and must be given back.

    Measuring the standard deviation of the pixels within ``±kσ`` alone underestimates σ,
    since the tails of the Gaussian have been cut. The factor is analytic — 1.3% at k = 3 —
    and ignoring it leaves a constant bias that nothing reveals as long as one only compares
    against oneself.
    """
    from math import erf, exp, pi, sqrt

    phi = exp(-0.5 * k * k) / sqrt(2.0 * pi)
    mass = erf(k / sqrt(2.0))
    if mass <= 0.0:
        return 1.0
    return sqrt(max(1.0 - 2.0 * k * phi / mass, 1e-6))


def _iterative_clip(values: np.ndarray, k: float, max_iter: int,
                   tol: float = 1e-4) -> tuple[float, np.ndarray]:
    """Clipping at k dispersions, until the dispersion stops moving.

    We start from the **MAD** and not from the standard deviation: on coefficients still full
    of stars, an initial standard deviation would be dominated by them and the first clipping
    would keep everything.
    """
    kept = np.ones(values.shape, dtype=bool)
    sigma = 1.4826 * float(np.median(np.abs(values - np.median(values))))
    if sigma <= 0.0:
        return 0.0, kept
    for _ in range(max_iter):
        kept = np.abs(values) <= k * sigma
        if not kept.any():
            break
        previous, sigma = sigma, float(np.std(values[kept])) / _truncation_correction(k)
        if sigma <= 0.0 or abs(sigma - previous) <= tol * previous:
            break
    return sigma, kept


def noise_ksigma(data: np.ndarray, k: float = 3.0, max_iter: int = 10) -> tuple[float, float]:
    """Noise estimated by k-sigma clipping on the first starlet layer.

    Returns ``(sigma, fraction)`` — the noise dispersion in the image's units, and the share
    of pixels that served to estimate it. A low fraction signals an image dense in structure,
    hence an estimate to be taken with reservation.
    """
    from .processes.multiscale import starlet_transform

    plan = np.asarray(data, dtype=np.float64)
    if plan.ndim != 2:
        raise ValueError(_t("noise_ksigma expects a 2D plane"))
    details, _ = starlet_transform(plan, 1)
    sigma, kept = _iterative_clip(details[0], float(k), int(max_iter))
    return sigma / _sigma_starlet(0), float(kept.mean())


def noise_mrs(data: np.ndarray, scales: int = 4, k: float = 3.0, max_iter: int = 10,
              support_scales: int = MRS_SUPPORT_SCALES) -> tuple[float, float] | None:
    """Noise estimated on the **multiresolution support** (Starck & Murtagh 1998).

    Any coefficient exceeding ``k`` times the expected noise dispersion at its scale is
    marked significant, those marks are unioned over every scale, and we measure only on what
    is left. The estimate is reinjected into the threshold, until convergence.

    Returns ``None`` if the support leaves too few free pixels — that is the signal to fall
    back on :func:`noise_ksigma` rather than return the dispersion of a nebula.
    """
    from scipy.ndimage import binary_dilation

    from .processes.multiscale import starlet_transform

    plan = np.asarray(data, dtype=np.float64)
    if plan.ndim != 2:
        raise ValueError(_t("noise_mrs expects a 2D plane"))
    details, _ = starlet_transform(plan, max(int(scales), 1))
    sigma, _ = _iterative_clip(details[0], float(k), int(max_iter))
    sigma /= _sigma_starlet(0)
    if sigma <= 0.0:
        return None

    fraction = 0.0
    for _ in range(int(max_iter)):
        support = np.zeros(plan.shape, dtype=bool)
        for j in range(min(int(support_scales), len(details))):
            support |= np.abs(details[j]) > float(k) * sigma * _sigma_starlet(j)
        # A star spills beyond its significant pixel: without dilation, its wings are still
        # counted as background and inflate the estimate.
        support = binary_dilation(support, iterations=1)
        free = ~support
        fraction = float(free.mean())
        if fraction < MRS_MIN_FRACTION:
            return None
        new_item = (float(np.std(details[0][free]))
                   / (_sigma_starlet(0) * _truncation_correction(float(k))))
        if new_item <= 0.0:
            return None
        if abs(new_item - sigma) <= 1e-4 * sigma:
            sigma = new_item
            break
        sigma = new_item
    return sigma, fraction


def split_cfa(plan: np.ndarray) -> list[np.ndarray]:
    """The four subplanes of a CFA mosaic (positions 00, 01, 10, 11).

    Indispensable for estimating the noise of an undebayered image: the four sites have
    different levels, and a filter mixing two neighboring pixels would measure their
    difference — that is to say the mosaic, not the noise.
    """
    h = (plan.shape[0] // 2) * 2
    w = (plan.shape[1] // 2) * 2
    trimmed = plan[:h, :w]
    return [trimmed[0::2, 0::2], trimmed[0::2, 1::2], trimmed[1::2, 0::2], trimmed[1::2, 1::2]]


def estimate_noise(data: np.ndarray, *, method: str = "mrs", k: float = 3.0,
                   scales: int = 4) -> dict:
    """Estimate the noise of a 2D plane, with a documented fallback.

    Returns ``{'sigma', 'fraction', 'method'}`` — ``method`` saying *what actually served*,
    and not what was asked for. That is what makes it possible to know, when reading a result
    back, that MRS did not converge.
    """
    if method == "mrs":
        result = noise_mrs(data, scales=scales, k=k)
        if result is not None:
            return {"sigma": result[0], "fraction": result[1], "method": "mrs"}
    sigma, fraction = noise_ksigma(data, k=k)
    return {"sigma": sigma, "fraction": fraction, "method": "ksigma"}
