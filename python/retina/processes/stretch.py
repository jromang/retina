"""Non-linear stretches: Arcsinh, AutoHistogram, Exponential, MaskedStretch.

Covers the intensity-transformation family (`ArcsinhStretch`, `AutoHistogram`,
`ExponentialTransformation`, `MaskedStretch`). Pure numpy + reuses the MTF/STF model
(`model.stf`) already present. Destructive (it transforms the pixels), unlike the STF.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..model.stf import mtf
from ..process.base import Parameter, Process
from ..process.registry import register


def adaptive_stretch_channel(
    ch: np.ndarray, noise_threshold: float, contrast_protection: float, resolution: int
) -> np.ndarray:
    """Core of AdaptiveStretch: a transfer curve derived from the data.

    We discretise the intensity into ``resolution`` levels, then walk every pair of adjacent
    pixels (right/bottom neighbours): a pair whose difference exceeds ``noise_threshold``
    votes to **increase** the contrast at that level (real detail), otherwise to **reduce**
    it (noise). The votes become the slope of a monotonic curve, integrated then normalised
    into [0,1]. ``contrast_protection`` caps the extreme slopes.
    """
    n = int(resolution)
    idx = np.clip(np.floor(np.clip(ch, 0.0, 1.0) * (n - 1)).astype(np.int64), 0, n - 1)
    thr = noise_threshold * (n - 1)
    pos = np.zeros(n, dtype=np.float64)
    neg = np.zeros(n, dtype=np.float64)
    for a_idx, b_idx in ((idx[:, :-1], idx[:, 1:]), (idx[:-1, :], idx[1:, :])):
        lo = np.minimum(a_idx, b_idx).ravel()
        diff = np.abs(a_idx - b_idx).ravel()
        real = diff > thr
        np.add.at(pos, lo[real], 1.0)          # real detail → dilate this level
        np.add.at(neg, lo[~real], 1.0)         # noise → compress this level
    deriv = np.maximum(pos - neg, 0.0)         # slope of the transfer (≥0 → monotonic)
    if contrast_protection > 0.0 and np.any(deriv > 0):
        cap = np.quantile(deriv[deriv > 0], 1.0 - 0.99 * float(contrast_protection))
        deriv = np.minimum(deriv, cap)
    deriv = deriv + 1e-6                        # floor: keeps the curve strictly increasing
    curve = np.cumsum(deriv)
    curve = (curve - curve[0]) / max(curve[-1] - curve[0], 1e-12)
    return curve[idx].astype(np.float32)


@register
class AdaptiveStretch(Process):
    """Data-driven adaptive stretch.

    Automatically builds a non-linear transfer curve from the differences between neighbouring
    pixels: dilates the intensity ranges rich in real detail, compresses those dominated by
    noise (``noise_threshold`` threshold). No manual handling of points; ``contrast_protection``
    limits contrast excesses. In colour, the same curve (derived from the luminance) applies to
    each channel → hues preserved.
    """

    process_id = "AdaptiveStretch"
    category = "IntensityTransformations"
    parameters = [
        Parameter("noise_threshold", "real", 1e-3, 1e-6, 0.5, label=N_("Noise threshold")),
        Parameter("contrast_protection", "real", 0.0, 0.0, 1.0,
                  label=N_("Contrast protection")),
        Parameter("resolution", "int", 4096, 64, 65536, label=N_("Curve resolution")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        nt = float(self.noise_threshold)
        cp = float(self.contrast_protection)
        res = int(self.resolution)
        if data.shape[2] >= 3:
            lum = data[:, :, :3].mean(axis=2)
            stretched = adaptive_stretch_channel(lum, nt, cp, res)
            ratio = np.divide(stretched, lum, out=np.ones_like(lum), where=lum > 1e-8)
            out = data.copy()
            out[:, :, :3] = np.clip(data[:, :, :3] * ratio[:, :, None], 0.0, 1.0)
            return out.astype(np.float32)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            out[:, :, c] = adaptive_stretch_channel(data[:, :, c], nt, cp, res)
        return out.astype(np.float32)


@register
class ArcsinhStretch(Process):
    """Colour-preserving arcsinh stretch.

    ``y = asinh(stretch·x) / asinh(stretch)`` after black-point removal. In colour, the factor
    is computed on the luminance and applied to each channel → hues are preserved (no drift
    towards white).
    """

    process_id = "ArcsinhStretch"
    category = "IntensityTransformations"
    parameters = [
        Parameter("stretch", "real", 10.0, 1.0, 1000.0, label=N_("Stretch factor")),
        Parameter("black_point", "real", 0.0, 0.0, 1.0, label=N_("Black point")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        s = max(float(self.stretch), 1.0 + 1e-6)
        bp = float(self.black_point)
        span = max(1.0 - bp, 1e-6)
        xn = np.clip((data - bp) / span, 0.0, 1.0)
        denom = np.arcsinh(s)

        if data.shape[2] >= 3:
            lum = xn[:, :, :3].mean(axis=2)
            stretched = np.arcsinh(s * lum) / denom
            ratio = np.divide(stretched, lum, out=np.ones_like(lum), where=lum > 1e-8)
            out = xn.copy()
            out[:, :, :3] = xn[:, :, :3] * ratio[:, :, None]
            return np.clip(out, 0.0, 1.0).astype(np.float32)

        return np.clip(np.arcsinh(s * xn) / denom, 0.0, 1.0).astype(np.float32)


@register
class AutoHistogram(Process):
    """Automatic per-channel stretch (robust median → target background), "baked" version.

    Derives an auto-stretch in the AutoSTF manner (median + MADN) then applies it to the
    pixels permanently. Reuses ``STF.auto_from_image`` (the single source of truth for the
    auto-stretch), which guarantees consistency with the display.
    """

    process_id = "AutoHistogram"
    category = "IntensityTransformations"
    parameters = [
        Parameter("target_background", "real", 0.25, 0.01, 0.9, label=N_("Target background")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from ..model.image import Image
        from ..model.stf import STF

        stf = STF.auto_from_image(Image(data), target_background=self.target_background)
        return stf.apply(data).astype(np.float32)


@register
class ExponentialTransformation(Process):
    """Exponential/power transformation (PIP / SMI)."""

    process_id = "ExponentialTransformation"
    category = "IntensityTransformations"
    parameters = [
        Parameter("type", "enum", "PIP", choices=("PIP", "SMI"), label=N_("Type")),
        Parameter("order", "real", 1.0, 0.1, 6.0, label=N_("Order")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        x = np.clip(data, 0.0, 1.0)
        p = float(self.order)
        # PIP (Power of Inverted Pixels) brightens the shadows; SMI, its mirror image,
        # darkens and compresses the highlights
        out = 1.0 - np.power(1.0 - x, p) if self.type == "PIP" else np.power(x, p)
        return out.astype(np.float32)


@register
class MaskedStretch(Process):
    """Iterative stretch with highlight protection.

    At each iteration, we compute the midtones that bring the median towards the target
    background, then apply the MTF weighted by a mask that **protects the bright pixels** (the
    stars stay contained instead of saturating).
    """

    process_id = "MaskedStretch"
    category = "IntensityTransformations"
    parameters = [
        Parameter("target_background", "real", 0.25, 0.01, 0.9, label=N_("Target background")),
        Parameter("iterations", "int", 20, 1, 200, label=N_("Iterations")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        target = float(self.target_background)
        out = np.clip(data, 0.0, 1.0).astype(np.float64).copy()
        for _ in range(int(self.iterations)):
            for c in range(out.shape[2]):
                ch = out[:, :, c]
                med = float(np.median(ch))
                if med <= 0.0 or med >= target:
                    continue
                m = mtf(target, med)  # midtones bringing med -> target
                stretched = np.asarray(mtf(m, ch), dtype=np.float64)
                mask = 1.0 - ch  # protects the highlights
                out[:, :, c] = ch * (1.0 - mask) + stretched * mask
        return np.clip(out, 0.0, 1.0).astype(np.float32)


# --- GeneralizedHyperbolicStretch ------------------------------------------------------
#
# The equations are those of the **published reference documentation** of the GHS module
# ("PixInsight Reference Documentation — GeneralizedHyperbolicStretch", Mike Cranfield,
# 2022-2023, ghsastro.co.uk), § 5.2. It is the *equations* that are taken over, not the code:
# the GHS module is under GPL-3, a mathematical formula is not. The implementation below is
# ours, in vectorised numpy.
#
# Two remarks the table of equations does not state and that one has to have seen:
#
# 1. **The sub-families are not on the same scale.** T'(0) equals D for the exponential, the
#    hyperbolic and the logarithmic, but 1 for the integral (b < 0). This has no consequence:
#    the final transformation is *normalised*, and a global scale factor on T cancels out
#    exactly there. It is even what makes the curve continuous in b across b = 0 and b = −1,
#    where the formulas change form.
# 2. **T is never evaluated on a negative argument**: T₂ and T₃ only call it on ``SP − x`` and
#    ``x − SP`` over their respective ranges. Hence the `maximum(..., 0)`, which avoid NaNs in
#    the branches that are not retained rather than correcting anything.

#: switching tolerance between sub-families. The b = −1, b = 0 and b = 1 formulas are the
#: continuous limits of the general formulas; we switch to them in their neighbourhood rather
#: than evaluating an exponent that tends to infinity.
GHS_EPS = 1e-9


def _ghs_base(u, D: float, b: float):
    """``T(u)`` and ``T'(u)`` of the base equations, for ``u ≥ 0``.

    Everything goes through ``log1p``/``expm1``: the forms ``(1 ± b·D·u)^(±1/b)`` become
    numerically unusable as soon as ``b`` approaches zero, whereas their exponential writing
    stays exact.
    """
    if abs(b + 1.0) < GHS_EPS:                    # logarithmic
        return np.log1p(D * u), D / (1.0 + D * u)
    if b < 0.0:                                   # integral
        w = np.log1p(-b * D * u)                  # b < 0 ⇒ argument > 1, never a domain error
        return (1.0 - np.exp(((b + 1.0) / b) * w)) / (D * (b + 1.0)), np.exp(w / b)
    if b < GHS_EPS:                               # exponential
        e = np.exp(-D * u)
        return 1.0 - e, D * e
    # hyperbolic — the harmonic form (b = 1) is its exact special case
    w = np.log1p(b * D * u)
    return 1.0 - np.exp(-w / b), D * np.exp(-((1.0 + b) / b) * w)


def _ghs_inverse_base(y, D: float, b: float):
    """``InvT(y)``, the inverse of :func:`_ghs_base` (§ 5.2.4 of the documentation)."""
    if abs(b + 1.0) < GHS_EPS:
        return np.expm1(y) / D
    if b < 0.0:
        w = np.log1p(np.maximum(-(b + 1.0) * D * y, -1.0 + 1e-12))
        return (1.0 - np.exp((b / (b + 1.0)) * w)) / (D * b)
    rest = np.log1p(-np.minimum(y, 1.0 - 1e-12))
    if b < GHS_EPS:
        return -rest / D
    return np.expm1(-b * rest) / (b * D)


def ghs_transfer(x, stretch_factor: float, local_intensity: float, sp: float,
                 lp: float, hp: float, inverse: bool = False):
    """Generalized hyperbolic transformation — the transfer function, on its own.

    The parameters are the user's: ``stretch_factor`` is ``ln(D+1)`` (that is what the slider
    sets), ``local_intensity`` is the ``b`` of the equations, ``sp``/``lp``/``hp`` the symmetry
    point and the shadow and highlight protections.

    The curve is built in four pieces: hyperbolic above ``sp``, its mirror image below, and
    two **linear segments** beyond ``lp`` and ``hp``, joined through the tangent — that is what
    "reserves" contrast for the shadows and the stars. The whole is normalised to run from 0
    to 1.

    A pure, vectorised function: it is the one the histogram panel reproduces in TypeScript to
    draw the curve, and it alone is authoritative.
    """
    x = np.asarray(x, dtype=np.float64)
    D = float(np.expm1(float(stretch_factor)))
    if D <= 0.0:
        return np.clip(x, 0.0, 1.0)               # zero factor ⇒ identity
    b = float(local_intensity)
    # The bounds are clamped instead of raising: an SP slider crossing LP must not make the
    # real-time preview fail on every frame.
    sp = float(np.clip(sp, 0.0, 1.0))
    lp = float(np.clip(lp, 0.0, sp))
    hp = float(np.clip(hp, sp, 1.0))

    # Joins: value and slope of the curve at the two protection points.
    t2_lp, t2p_lp = _ghs_base(sp - lp, D, b)
    t2_lp = -t2_lp                                # T₂(x) = −T(SP − x)
    t3_hp, t3p_hp = _ghs_base(hp - sp, D, b)
    t1_0 = t2p_lp * (0.0 - lp) + t2_lp            # T₁(0)
    t4_1 = t3p_hp * (1.0 - hp) + t3_hp            # T₄(1)
    span = t4_1 - t1_0
    if not np.isfinite(span) or abs(span) < 1e-15:
        return np.clip(x, 0.0, 1.0)

    if not inverse:
        t2 = -_ghs_base(np.maximum(sp - x, 0.0), D, b)[0]
        t3 = _ghs_base(np.maximum(x - sp, 0.0), D, b)[0]
        y = np.where(
            x < lp, t2p_lp * (x - lp) + t2_lp,
            np.where(x < sp, t2,
                     np.where(x < hp, t3, t3p_hp * (x - hp) + t3_hp)))
        return np.clip((y - t1_0) / span, 0.0, 1.0)

    # Inverse: we go back to non-normalised coordinates, then invert piece by piece.
    xp = t1_0 + x * span
    y = np.where(
        x < (t2_lp - t1_0) / span,
        lp + (xp - t2_lp) / t2p_lp,
        np.where(x < (0.0 - t1_0) / span,
                 sp - _ghs_inverse_base(np.maximum(-xp, 0.0), D, b),
                 np.where(x < (t3_hp - t1_0) / span,
                          sp + _ghs_inverse_base(np.maximum(xp, 0.0), D, b),
                          hp + (xp - t3_hp) / t3p_hp)))
    return np.clip(y, 0.0, 1.0)


@register
class GeneralizedHyperbolicStretch(Process):
    """Generalized hyperbolic stretch (GHS) — five parameters, one curve.

    The community tool that became a standard, and has remained at the heart of award-winning
    processing. What it brings over a `HistogramTransformation`: the stretch **concentrates**
    around a chosen symmetry point, with an adjustable intensity, instead of acting uniformly.
    One spends one's contrast "budget" where the data are.
    """

    process_id = "GeneralizedHyperbolicStretch"
    category = "IntensityTransformations"
    parameters = [
        Parameter("stretch_factor", "real", 0.0, 0.0, 20.0,
                  label=N_("Stretch factor (ln(D+1))")),
        Parameter("local_intensity", "real", 0.0, -5.0, 15.0, label=N_("Local intensity (b)")),
        Parameter("symmetry_point", "real", 0.0, 0.0, 1.0, label=N_("Symmetry point (SP)")),
        Parameter("protect_shadows", "real", 0.0, 0.0, 1.0, label=N_("Protect shadows (LP)")),
        Parameter("protect_highlights", "real", 1.0, 0.0, 1.0,
                  label=N_("Protect highlights (HP)")),
        Parameter("mode", "enum", "rgb", choices=("rgb", "lightness", "colour"),
                  label=N_("Mode")),
        Parameter("clip_type", "enum", "rescale", choices=("clip", "rescale"),
                  label=N_("Clip type")),
        Parameter("invert", "bool", False, label=N_("Invert")),
    ]

    def _courbe(self, values):
        return ghs_transfer(values, self.stretch_factor, self.local_intensity,
                            self.symmetry_point, self.protect_shadows,
                            self.protect_highlights, inverse=bool(self.invert))

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if self.mode == "lightness" and data.shape[2] >= 3:
            return self._lightness(data)
        if self.mode == "colour" and data.shape[2] >= 3:
            return self._colour(data)
        return self._courbe(np.clip(data, 0.0, 1.0)).astype(np.float32)

    def _lightness(self, data: np.ndarray) -> np.ndarray:
        """Stretches the CIE L* lightness alone, chrominance untouched."""
        from skimage.color import lab2rgb, rgb2lab

        rgb = np.clip(data[:, :, :3], 0.0, 1.0)
        lab = rgb2lab(rgb)
        lab[:, :, 0] = self._courbe(lab[:, :, 0] / 100.0) * 100.0
        output = data.copy()
        output[:, :, :3] = np.clip(lab2rgb(lab), 0.0, 1.0)
        return output.astype(np.float32)

    def _colour(self, data: np.ndarray) -> np.ndarray:
        """Stretches the mean of the channels and applies the **ratio** — the arcsinh route.

        The proportions between channels are preserved exactly, hence saturation too; this is
        what a per-channel stretch lacks, as it brings the channels closer to one another and
        washes the image out. The price is that the result may exceed 1, hence
        ``clip_type``.
        """
        rgb = np.clip(data[:, :, :3], 0.0, 1.0)
        z = rgb.mean(axis=2)
        report = np.divide(self._courbe(z), z, out=np.ones_like(z), where=z > 1e-8)
        etire = rgb * report[:, :, None]
        if self.clip_type == "rescale":
            # Per pixel, as the reference does: a pixel that overflows is brought back as a
            # whole, which keeps its hue. A clip would make it drift towards white.
            top = np.maximum(etire.max(axis=2), 1.0)
            etire = etire / top[:, :, None]
        output = data.copy()
        output[:, :, :3] = np.clip(etire, 0.0, 1.0)
        return output.astype(np.float32)
