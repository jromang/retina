"""Narrowband — inject Hα/OIII/SII into an RGB image, and normalise an SHO set.

Two gestures everyone performs by hand in PixelMath, and that deserve to be replayable
processes. They share one building block: the **linear fit** of one image onto another, which
answers the only hard question — *at what scale* to put two images acquired through different
filters, different exposure times and a different sky.

Repository convention: an input image is designated by the **identifier of its view**,
resolved through ``retina.process.context.resolve_image_full``. This is what
``ChannelCombination`` and ``LRGBCombination`` already do.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register

#: usual target channels of each emission line, in an SHO/HOO composition
CHANNELS = ("red", "green", "blue")


def _resolve(identifier: str, shape: tuple[int, int], quoi: str) -> np.ndarray:
    """The 2D plane of a named view, checked for geometry."""
    from ..process import context

    arr = context.resolve_image_full(identifier)
    if arr is None:
        raise ValueError(_t("{who}: view not found ({id!r})").format(who=quoi, id=identifier))
    if arr.shape[:2] != shape:
        raise ValueError(
            _t("{who}: view {id!r} is {view_shape}, the image is {shape} — they must share "
               "the same geometry (register them first).").format(
                who=quoi, id=identifier, view_shape=arr.shape[:2], shape=shape))
    plan = arr.mean(axis=2) if arr.ndim == 3 and arr.shape[2] > 1 else arr[:, :, 0]
    return np.clip(plan.astype(np.float64), 0.0, None)


def _linear_fit(source: np.ndarray, reference: np.ndarray,
                         mask: np.ndarray | None = None) -> np.ndarray:
    """Brings ``source`` to the scale of ``reference`` through a least-squares line.

    This is the only honest way to compare two images taken through different filters: their
    units have no reason to coincide, and comparing them raw amounts to comparing minutes
    with metres.

    **Degenerate case, and it does happen**: if the retained pixels are all at the same
    value — the perfectly flat background of a synthetic image, or a heavily denoised one —
    the line is not defined, its slope then depending on numerical noise alone. We fall back
    on the **offset**, which always is. Doing nothing would be worse: the process would look
    like it ran without acting.
    """
    a, b = source.ravel(), reference.ravel()
    if mask is not None:
        kept = mask.ravel()
        if kept.sum() >= 16:
            a, b = a[kept], b[kept]
    if a.size < 2:
        return source.copy()
    span = float(np.std(a))
    if span <= 1e-6 * max(abs(float(np.mean(a))), 1e-6):
        return source + (float(np.median(b)) - float(np.median(a)))
    slope, ordonnee = np.polyfit(a, b, 1)
    return source * float(slope) + float(ordonnee)


def scale_from_stars(source: np.ndarray, reference: np.ndarray,
                        radius: float = 4.0) -> float | None:
    """Scale factor between two images, by the **median of the stellar flux ratios**.

    A pixel-to-pixel regression does not work here, and it took watching it fail to
    understand why: the emission pixels have the largest abscissae, hence the most leverage,
    and they pull the slope towards themselves. Measured on a synthetic field whose true scale
    was 0.5: a naive regression returns 0.042, and iterative clipping makes things *worse* —
    it rejects the healthy stars, whose residual is larger than that of the emission points
    under an already collapsed slope.

    The right estimator is **per star**: we sum the flux of each one in both images, and take
    the **median** of the ratios. A star sitting on the nebula gives an aberrant ratio, but it
    is only one point among the others — the median ignores it, where least squares obeyed it.
    It is also, quite simply, the way two images are brought to the same scale in astronomy.

    Returns ``None`` if there are not enough stars for the median to mean anything.
    """
    from .stars import detect_sources

    try:
        sources = detect_sources(reference, 3.0, 5.0)
    except Exception:
        return None
    if sources is None or len(sources) < 5:
        return None
    xcol = "xcentroid" if "xcentroid" in sources.colnames else "x_centroid"
    ycol = "ycentroid" if "ycentroid" in sources.colnames else "y_centroid"
    fond_source = float(np.median(source))
    fond_reference = float(np.median(reference))
    half = int(np.ceil(radius))
    height, width = reference.shape

    reports = []
    for x, y in zip(np.asarray(sources[xcol]), np.asarray(sources[ycol]), strict=True):
        xi, yi = int(round(float(x))), int(round(float(y)))
        if not (half <= xi < width - half and half <= yi < height - half):
            continue
        slice_ = (slice(yi - half, yi + half + 1), slice(xi - half, xi + half + 1))
        flux_source = float(np.sum(source[slice_] - fond_source))
        flux_reference = float(np.sum(reference[slice_] - fond_reference))
        if flux_source > 0.0 and flux_reference > 0.0:
            reports.append(flux_reference / flux_source)
    if len(reports) < 5:
        return None
    return float(np.median(reports))


def background_pixels(plans: list[np.ndarray], k: float = 3.0) -> np.ndarray:
    """The pixels that **all** the given planes hold to be background.

    All of them, not each one its own: a fit is made over *common* pixels, otherwise we
    compare two different populations and the resulting line means nothing.

    Significance is that of the multiresolution support, the same one used to measure the
    noise (:mod:`retina.noise_estimation`).
    """
    from ..noise_estimation import STARLET_SIGMA
    from .multiscale import starlet_transform

    commun = np.ones(plans[0].shape, dtype=bool)
    for plan in plans:
        details, _ = starlet_transform(plan, 2)
        sigma = 1.4826 * float(np.median(np.abs(details[0] - np.median(details[0]))))
        if sigma <= 0.0:
            continue
        significatif = np.zeros(plan.shape, dtype=bool)
        for j, layer in enumerate(details):
            significatif |= np.abs(layer) > k * sigma * (STARLET_SIGMA[j] / STARLET_SIGMA[0])
        commun &= ~significatif
    return commun


@register
class NBRGBCombination(Process):
    """Injects one or more narrow emission lines into a broadband RGB image.

    The principle: a narrowband image shows the line with a contrast the broadband cannot
    have — there it is drowned in the continuum. We first **fit** the narrow band to the scale
    of the target channel — **on the background pixels only** — then extract what **exceeds**
    the channel, that is, the line signal the broad band does not see, and add an adjustable
    fraction of it.

    **The scale comes from the stars**, and it took two failed attempts to be convinced of it.
    Fitting over the whole image makes the narrow band coincide with the channel *everywhere*,
    nebula included: the excess is then zero and the process does nothing. Fitting on the
    background is no better — there we correlate two independent noises, whose slope is zero
    by construction, and we obtain a constant. The stars, on the other hand, are **continuum**
    sources present in both images: the **median of the ratios of their flux** *is* the
    transmission and exposure factor between the two, and it is robust to the few stars
    sitting on the nebula. See :func:`scale_from_stars`, which also says why a pixel-to-pixel
    regression fails here.

    The **offset**, for its part, comes from the background: setting the scale and the
    pedestal on the same points would lift the sky over the whole image. Each one where it is
    measurable.

    Taking the excess and not the whole image is what preserves the stars: a star is bright in
    both, so it does not exceed, and it is not injected twice.

    Two ways of dosing:

    - ``manual`` (default): ``strength`` alone. This is the setting one wants in practice,
      because "how much Hα" is an aesthetic judgement, not a physical quantity.
    - ``bandwidth``: ``strength`` multiplied by the ratio of the bandwidths. The line then
      contributes as it would through the broad filter — physically grounded, but the result
      is **discreet** (a 7/100 ratio gives 7 %), which is surprising if one ignores it.
    """

    process_id = "NBRGBCombination"
    category = "ColorCalibration"
    supports_realtime = False
    parameters = [
        Parameter("ha_view", "view", "", label=N_("Ha view")),
        Parameter("oiii_view", "view", "", label=N_("OIII view")),
        Parameter("sii_view", "view", "", label=N_("SII view")),
        Parameter("ha_channel", "enum", "red", choices=CHANNELS, label=N_("Ha target channel")),
        Parameter("oiii_channel", "enum", "green", choices=CHANNELS,
                  label=N_("OIII target channel")),
        Parameter("sii_channel", "enum", "red", choices=CHANNELS,
                  label=N_("SII target channel")),
        Parameter("mode", "enum", "manual", choices=("manual", "bandwidth"),
                  label=N_("Weighting")),
        Parameter("strength", "real", 0.5, 0.0, 1.0, label=N_("Strength")),
        Parameter("nb_bandwidth", "real", 7.0, 0.1, 300.0,
                  label=N_("Narrowband bandwidth (nm)")),
        Parameter("rgb_bandwidth", "real", 100.0, 0.1, 1000.0,
                  label=N_("Broadband bandwidth (nm)")),
    ]

    def _weights(self) -> float:
        weights = float(np.clip(self.strength, 0.0, 1.0))
        if self.mode == "bandwidth":
            weights *= float(self.nb_bandwidth) / max(float(self.rgb_bandwidth), 1e-6)
        return weights

    @staticmethod
    def _mettre_a_lechelle(plan: np.ndarray, target: np.ndarray) -> np.ndarray:
        """Scale taken from the stars, offset taken from the background.

        Each one where it is measurable: the scale on continuum sources present in both
        images, the pedestal on the sky. Setting the intercept from the stars would lift the
        background of the whole image, since we would be extrapolating far from the measured
        points.
        """
        factor = scale_from_stars(plan, target)
        fitted = plan * factor if factor else plan.copy()
        background = background_pixels([plan, target])
        if background.any():
            fitted = fitted + (float(np.median(target[background]))
                               - float(np.median(fitted[background])))
        return fitted

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 3:
            raise ValueError(_t("NBRGBCombination requires a color (RGB) image."))
        raies = [(self.ha_view, self.ha_channel), (self.oiii_view, self.oiii_channel),
                 (self.sii_view, self.sii_channel)]
        if not any(view for view, _ in raies):
            raise ValueError(
                _t("NBRGBCombination: no emission line provided. Set at least ha_view, "
                   "oiii_view or sii_view (a view identifier)."))

        weights = self._weights()
        output = np.clip(data, 0.0, 1.0).astype(np.float64)
        shape = data.shape[:2]
        for view, channel in raies:
            if not view:
                continue
            self._checkpoint()
            index_ = CHANNELS.index(channel)
            target = output[:, :, index_]
            plan = _resolve(view, shape, self.process_id)
            fitted = self._mettre_a_lechelle(plan, target)
            # What exceeds the channel, and nothing else: a star bright in both does not
            # exceed, hence is not added a second time.
            exces = np.clip(fitted - target, 0.0, None)
            output[:, :, index_] = target + weights * exces
        return np.clip(output, 0.0, 1.0).astype(np.float32)


@register
class NarrowbandNormalization(Process):
    """Brings the channels of an SHO composition to the same **background** scale.

    Three narrow filters acquired separately have neither the same sky background nor the same
    apparent gain: the palette that comes out of them is dominated by those differences rather
    than by the signal. So we fit each channel onto a reference channel — but **on the
    background pixels only**.

    That is the whole point. A fit over the whole image would be pulled by the emission
    regions, which are precisely what we want to see differ from one channel to another:
    aligning Hα onto OIII everywhere would amount to erasing what we are trying to show. The
    background pixels are designated by the **multiresolution support**
    (:mod:`retina.noise_estimation`), which is already used to measure the noise.

    Works for a **mono** set (three views) as well as for an already composed **colour**
    image: without named views, it is the image's three channels that are normalised against
    one another.
    """

    process_id = "NarrowbandNormalization"
    category = "ColorCalibration"
    supports_realtime = False
    parameters = [
        Parameter("reference", "enum", "green", choices=CHANNELS,
                  label=N_("Reference channel")),
        Parameter("red_view", "view", "", label=N_("Red channel view")),
        Parameter("green_view", "view", "", label=N_("Green channel view")),
        Parameter("blue_view", "view", "", label=N_("Blue channel view")),
        Parameter("k_sigma", "real", 3.0, 1.0, 10.0, label=N_("Background threshold (k·σ)")),
        Parameter("match_scale", "bool", True, label=N_("Match scale as well as offset")),
    ]

    def _plans(self, data: np.ndarray) -> list[np.ndarray]:
        shape = data.shape[:2]
        views = (self.red_view, self.green_view, self.blue_view)
        if any(views):
            if not all(views):
                raise ValueError(
                    _t("NarrowbandNormalization: set all three views, or none (in which case "
                       "the image's three channels are normalized)."))
            return [_resolve(v, shape, self.process_id) for v in views]
        if data.shape[2] < 3:
            raise ValueError(
                _t("NarrowbandNormalization: without named views, a 3-channel image is required."))
        return [np.clip(data[:, :, c], 0.0, None).astype(np.float64) for c in range(3)]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        plans = self._plans(data)
        background = background_pixels(plans, float(self.k_sigma))
        index_ = CHANNELS.index(self.reference)
        reference = plans[index_]

        output = np.empty((*plans[0].shape, 3), dtype=np.float64)
        for c, plan in enumerate(plans):
            self._checkpoint()
            if c == index_:
                output[:, :, c] = plan
            elif self.match_scale:
                output[:, :, c] = _linear_fit(plan, reference, background)
            else:
                # Offset only: we align the backgrounds without touching the contrast, which
                # is sometimes preferable — the relative gain of the filters is then a piece
                # of information we do not want to erase.
                deviation = (float(np.median(reference[background]))
                             - float(np.median(plan[background]))
                         if background.any() else 0.0)
                output[:, :, c] = plan + deviation
        return np.clip(output, 0.0, 1.0).astype(np.float32)
