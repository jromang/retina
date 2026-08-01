"""Gradients & mosaic: GradientCorrection, MultiscaleGradientCorrection, GradientMergeMosaic.

Complements the background extraction (ABE/DBE) with a polynomial gradient removal and with
the merging of mosaic panels with background equalization. numpy/scipy.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def _poly_surface(ch: np.ndarray, degree: int, sigma: float = 3.0) -> np.ndarray:
    """Fits a robust 2D polynomial surface (sigma-clip) and returns it sampled."""
    from astropy.stats import sigma_clip

    h, w = ch.shape
    ys, xs = np.mgrid[0:h, 0:w]
    xn = (xs / max(w - 1, 1)).ravel()
    yn = (ys / max(h - 1, 1)).ravel()
    terms = [xn**i * yn**j for i in range(degree + 1) for j in range(degree + 1 - i)]
    A = np.stack(terms, axis=1)
    z = ch.ravel()
    mask = ~np.ma.getmaskarray(sigma_clip(z, sigma=sigma))  # ignores stars/objects
    coef, *_ = np.linalg.lstsq(A[mask], z[mask], rcond=None)
    return (A @ coef).reshape(h, w)


@register
class GradientCorrection(Process):
    """Removes a background gradient modeled by a robust polynomial surface."""

    process_id = "GradientCorrection"
    category = "BackgroundModelization"
    parameters = [
        Parameter("degree", "int", 1, 1, 5, label=N_("Polynomial degree")),
        Parameter("pedestal", "real", 0.1, 0.0, 1.0, label=N_("Pedestal")),
        Parameter("subtract", "bool", True, label=N_("Subtract (otherwise: model)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        d = int(self.degree)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            surf = _poly_surface(data[:, :, c], d)
            out[:, :, c] = (data[:, :, c] - surf + self.pedestal) if self.subtract else surf
        return np.clip(out, 0.0, 1.0).astype(np.float32)


def _affine_robuste(target: np.ndarray, model: np.ndarray,
                    sigma: float = 3.0, tours: int = 3) -> tuple[float, float]:
    """Fits ``target ≈ a·modele + b``, discarding outliers (sigma-clip on the residual).

    The clipping is what makes the fit usable on a survey reference: the halos of the bright
    stars and the non-linear areas of photographic plates are precisely the points that would
    pull the line towards themselves.
    """
    x = model.ravel().astype(np.float64)
    y = target.ravel().astype(np.float64)
    kept = np.isfinite(x) & np.isfinite(y)
    a, b = 0.0, float(np.median(y[kept])) if kept.any() else 0.0
    for _ in range(tours):
        if kept.sum() < 8:
            break
        A = np.stack([x[kept], np.ones(int(kept.sum()))], axis=1)
        coef, *_ = np.linalg.lstsq(A, y[kept], rcond=None)
        a, b = float(coef[0]), float(coef[1])
        residual = y - (a * x + b)
        deviation = 1.4826 * float(np.median(np.abs(residual[kept] - np.median(residual[kept]))))
        if deviation <= 0.0:
            break
        kept = kept & (np.abs(residual - np.median(residual[kept])) < sigma * deviation)
    return a, b


@register
class MultiscaleGradientCorrection(Process):
    """Removes the large-scale gradient (starlet residual) while preserving the fine detail.

    Two modes, depending on whether a **reference** is supplied or not.

    *Without a reference*, the starlet residual — the very low frequency — is replaced by its
    median: everything large-scale is taken to be gradient. That is effective on a
    light-pollution gradient, but blind: an extended nebulosity, an IFN, the tail of a galaxy
    are large-scale too, and go away with the rest.

    *With a reference*: an image of the same field **without gradient** (typically synthesized
    by :class:`SurveyReference` from an all-sky survey) tells what *shape* the sky really has
    at large scale. What the image residual carries in addition is the gradient, and nothing
    else. The reference is used for its shape only: a robust affine fit per channel absorbs
    scale and offset, which makes the algorithm insensitive to the fact that a DSS plate is
    neither linear nor photometric. Its stars live in the detail layers, which are thrown
    away.
    """

    process_id = "MultiscaleGradientCorrection"
    category = "BackgroundModelization"
    parameters = [
        Parameter("scale", "int", 7, 3, 12, label=N_("Gradient scale (layers)")),
        Parameter("pedestal", "real", 0.1, 0.0, 1.0, label=N_("Pedestal")),
        Parameter("reference", "view", "", label=N_("Reference view (no gradient)")),
        Parameter("reference_path", "str", "", label=N_("Reference file")),
    ]

    def _large_scale_reference(self, shape_hw: tuple[int, int]) -> np.ndarray | None:
        """Starlet residual of the reference, resampled to the geometry of the image.

        The resampling is legitimate because only the large scale is consumed: the reference
        is requested subsampled (it then weighs a few hundred KB), and the real-time preview,
        for its part, uses a **decimated** image — the two grids cover the same celestial
        footprint, which is all that is required.
        """
        from .multiscale import starlet_transform
        from .registration import _resolve_reference

        if not self.reference and not self.reference_path:
            return None
        arr = _resolve_reference(str(self.reference), str(self.reference_path))
        plan = arr[:, :, 0] if arr.ndim == 3 else arr
        if plan.shape != shape_hw:
            from scipy.ndimage import zoom

            facteurs = (shape_hw[0] / plan.shape[0], shape_hw[1] / plan.shape[1])
            plan = zoom(plan.astype(np.float64), facteurs, order=1)
            # `zoom` rounds: we crop or pad to the exact pixel rather than let a
            # one-pixel difference make the fit fail.
            plan = plan[: shape_hw[0], : shape_hw[1]]
            if plan.shape != shape_hw:
                plan = np.pad(plan, ((0, shape_hw[0] - plan.shape[0]),
                                     (0, shape_hw[1] - plan.shape[1])), mode="edge")
        _details, residual = starlet_transform(plan, int(self.scale))
        return residual

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from .multiscale import starlet_transform

        n = int(self.scale)
        ref_res = self._large_scale_reference(data.shape[:2])
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            details, residual = starlet_transform(data[:, :, c], n)
            sky = self._sky(residual, ref_res)
            out[:, :, c] = sum(details) + sky + self.pedestal
        return np.clip(out, 0.0, 1.0).astype(np.float32)

    def _sky(self, residual: np.ndarray, ref_res: np.ndarray | None):
        """What the sky is really worth at large scale — a scalar, or a surface."""
        if ref_res is None:
            return np.median(residual)
        if not np.isfinite(ref_res).any() or float(np.std(ref_res)) <= 0.0:
            self._sans_reference(N_("Reference has no large-scale structure"))
            return np.median(residual)
        a, b = _affine_robuste(residual, ref_res)
        if not np.isfinite(a) or a <= 0.0:
            # A null or negative slope says that the reference explains nothing of the
            # residual: mismatched field, survey not covering the area, image already
            # corrected. Following it would invent a gradient instead of removing one.
            self._sans_reference(N_("Reference does not match the image background"))
            return np.median(residual)
        return a * ref_res + b

    @staticmethod
    def _sans_reference(pattern: str) -> None:
        """Says why the reference was discarded — a silent fallback would suggest an effect."""
        from ..process import context

        try:
            app = context.get_application()
            if app is not None:
                app.notify(
                    _t("{reason} — falling back to the reference-free correction.").format(
                        reason=_t(pattern)
                    ),
                    kind="warning", source="MultiscaleGradientCorrection",
                )
        except Exception:  # headless, no application: of no importance
            pass


@register
class SurveyReference(Process):
    """Synthesizes a **gradient-free** reference image of the field, from a sky survey.

    **Global** process: it produces a new window, without touching the pixels of the source.
    The field is the one of the astrometric solution of the target window, and the CDS
    ``hips2fits`` service returns an image directly on that grid — there is therefore no
    database to download and no reprojection to perform.

    The result is then handed to :class:`MultiscaleGradientCorrection` through its
    ``reference`` parameter. This two-step approach is deliberate: the reference is a window,
    hence **inspectable** (Blink, linked views, before/after curtain) before it is used, and
    reusable for ten correction attempts without going back over the network. A correction
    whose reference stays buried inside the tool allows neither.

    In headless/test use, ``set_reference(array)`` avoids the network request.
    """

    process_id = "SurveyReference"
    category = "BackgroundModelization"
    is_global = True
    supports_realtime = False
    parameters = [
        Parameter("view_id", "view", "", label=N_("Source window (empty = active)")),
        Parameter("survey", "enum", "dss2-red",
                  choices=("dss2-red", "dss2-blue", "panstarrs-g", "panstarrs-r",
                           "panstarrs-i", "halpha", "custom"),
                  label=N_("Sky survey")),
        Parameter("hips_id", "str", "", label=N_("HiPS id"),
                  visible_when=("survey", ("custom",))),
        Parameter("max_size", "int", 1024, 0, 8192, label=N_("Max size (px, 0 = full)")),
        Parameter("use_cache", "bool", True, label=N_("Use the local cache")),
        Parameter("new_image_id", "str", "", label=N_("New image id")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._reference = None  # plane supplied explicitly (headless, tests)

    def set_reference(self, plan) -> SurveyReference:
        """Supplies the reference instead of fetching it — short-circuits the network."""
        self._reference = np.asarray(plan, dtype=np.float32)
        return self

    def execute_global(self, app) -> bool:
        from .. import hips as hips_module
        from ..model.image import Image

        win = self._source_window(app)
        shape = win.main_view.image.data.shape[:2]
        if self._reference is not None:
            plan = self._reference
            ref_wcs, _forme = hips_module.reduced_wcs(win.wcs, shape, int(self.max_size))
            identifier = self.hips_id or self.survey
        else:
            identifier = hips_module.hips_id_for(str(self.survey), str(self.hips_id))
            plan, ref_wcs = hips_module.fetch(
                win.wcs, shape, str(self.survey), hips_id=str(self.hips_id),
                max_size=int(self.max_size), use_cache=bool(self.use_cache),
            )

        reference = app.new_window(
            Image(plan[:, :, None] if plan.ndim == 2 else plan),
            window_id=self.new_image_id or f"{win.id}_{self.survey}",
        )
        # The reference is itself plate-solved — that is what makes it possible to overlay it
        # on the source (linked views, celestial readout) and to check by eye that we really
        # are looking at the same field before correcting anything at all.
        reference.wcs = ref_wcs
        reference.keywords = {
            "HIPSID": identifier,
            "HIPSSURV": str(self.survey),
            "HISTORY": f"Retina SurveyReference from {identifier}",
        }
        return True

    def _source_window(self, app):
        if self.view_id:
            win = next((w for w in app.windows
                        if w.id == self.view_id or w.main_view.id == self.view_id), None)
            if win is None:
                raise ValueError(
                    _t("Window not found: {view_id!r}").format(view_id=self.view_id))
        else:
            win = app.active_window
        if win is None or win.wcs is None:
            raise ValueError(
                _t("SurveyReference requires an astrometric solution (run PlateSolve).")
            )
        return win


@register
class GradientMergeMosaic(Process):
    """Merges the current view with another (panel), background equalized, over the useful areas.

    Equalizes the background of the two panels (median offset over the overlap) then composes:
    inside the overlap, the mean; elsewhere, whichever panel is non-zero. The images must
    already be projected onto the same grid (StarAlignment/PlateSolve).
    """

    process_id = "GradientMergeMosaic"
    category = "BackgroundModelization"
    is_maskable = False
    parameters = [Parameter("other", "view", "", label=N_("Other panel (view)"))]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from ..process import context

        if not self.other:
            return data.copy()
        other = context.resolve_image_full(self.other)
        if other is None or other.shape != data.shape:
            return data.copy()
        a, b = data, other
        va, vb = a.sum(axis=2) > 0, b.sum(axis=2) > 0
        overlap = va & vb
        if overlap.any():  # equalizes the background of b onto a over the overlap
            offset = float(np.median(a[overlap]) - np.median(b[overlap]))
            b = b + offset
        out = np.where(va[:, :, None] & ~vb[:, :, None], a,
                       np.where(vb[:, :, None] & ~va[:, :, None], b, 0.5 * (a + b)))
        return np.clip(out, 0.0, 1.0).astype(np.float32)
