"""Star registration (StarAlignment) via astroalign.

Single-image: aligns the active view onto a reference (another view by id, or a file).
The transform is estimated on the luminance then applied to each channel.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def _resolve_reference(reference_id: str, reference_path: str) -> np.ndarray:
    """Loads the reference image (file takes priority, otherwise view by id).

    Raises if the reference is requested but not found: returning the image unchanged would
    produce a result that is neither registered nor normalized, and undetectable after the fact.
    """
    if reference_path:
        from ..io import load_image_array

        return load_image_array(reference_path)
    if reference_id:
        from ..process import context

        arr = context.resolve_image_full(reference_id)
        if arr is not None:
            return arr
        raise ValueError(_t("Reference not found: view {id!r}").format(id=reference_id))
    raise ValueError(_t("No reference provided (reference_id or reference_path)"))


#: settings of the registration star detection — the auxiliary key of the :class:`StarCache`
#: (changing a parameter creates a distinct entry rather than serving back a wrong one)
ALIGN_STARS_SETTINGS = {"detector": "astroalign-sep", "detection_sigma": 5,
                        "min_area": 5, "max_points": 50}


def detect_alignment_stars(lum: np.ndarray) -> list[list[float]]:
    """Positions ``(x, y)`` of the registration stars, sorted by decreasing flux.

    The **same** detection that ``astroalign.find_transform`` would perform internally (sep,
    same thresholds): the hidden path and the direct path produce the same control points, hence
    the same transformation. Returns ``[]`` if the private API disappears from a future
    version — the cache then switches itself off without breaking anything.
    """
    import astroalign

    finder = getattr(astroalign, "_find_sources", None)
    if finder is None:  # pragma: no cover - depends on the astroalign version
        return []
    stars = finder(np.ascontiguousarray(lum, dtype=np.float32),
                   detection_sigma=ALIGN_STARS_SETTINGS["detection_sigma"],
                   min_area=ALIGN_STARS_SETTINGS["min_area"])
    limit = int(ALIGN_STARS_SETTINGS["max_points"])
    return [[float(x), float(y)] for x, y in stars[:limit]]


@register
class StarAlignment(Process):
    process_id = "StarAlignment"
    category = "ImageRegistration"
    supports_realtime = False  # star detection + geometry of the reference
    parameters = [
        Parameter("reference_id", "str", "", label=N_("Reference view (id)")),
        Parameter("reference_path", "path", "", label=N_("…or reference file")),
        Parameter("fill_value", "real", 0.0, 0.0, 1.0, label=N_("Out-of-field fill"),
                  tooltip=N_("Value of the areas not observed after registration")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Control points supplied by the pipeline (per-file star cache) — outside of
        # Parameter: this is execution state, not a serializable setting. Without them, the
        # historical behavior (astroalign's internal detection) is unchanged.
        self.source_stars: list | None = None
        self.reference_stars: list | None = None
        self._ref_data: np.ndarray | None = None
        self._ref_data_path: str | None = None

    def _reference(self) -> np.ndarray:
        if self.reference_path:
            # Memoized: the pipeline applies the same instance to every frame of the group,
            # and reloading the reference from disk on every exposure was the second cost
            # of registration after detection.
            if self._ref_data is not None and self._ref_data_path == self.reference_path:
                return self._ref_data
            from ..io import load_image_array

            self._ref_data = load_image_array(self.reference_path)
            self._ref_data_path = str(self.reference_path)
            return self._ref_data
        if self.reference_id:
            from ..process import context

            arr = context.resolve_image_full(self.reference_id)
            if arr is not None:
                return arr
        raise ValueError(_t("StarAlignment: no reference (reference_id or reference_path)"))

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import astroalign

        ref = self._reference()
        src_lum = data.mean(axis=2)
        ref_lum = ref.mean(axis=2)
        self._progress(0.0, _t("Matching stars"))
        if (self.source_stars and self.reference_stars
                and len(self.source_stars) >= 3 and len(self.reference_stars) >= 3):
            # control points already known (per-file cache): find_transform accepts lists of
            # coordinates and then skips its own sep detection
            transform, _ = astroalign.find_transform(
                np.asarray(self.source_stars, dtype=float),
                np.asarray(self.reference_stars, dtype=float))
        else:
            transform, _ = astroalign.find_transform(src_lum, ref_lum)

        out = np.empty((ref.shape[0], ref.shape[1], data.shape[2]), dtype=np.float32)
        channels = data.shape[2]
        for c in range(channels):
            self._progress(0.5 + 0.5 * c / channels, _t("Resampling {n}/{total}").format(
                n=c + 1, total=channels))
            # Explicit `fill_value`: by default astroalign fills the out-of-field areas with
            # the MEDIAN of the image. That avoids a hard edge on screen, but manufactures
            # plausible sky where nothing was observed — and the integration would then
            # average this invented sky with real sky. A zero tells the truth, and lets
            # `AutoCrop` find the area actually covered.
            registered, _ = astroalign.apply_transform(
                transform, data[:, :, c], ref_lum, fill_value=float(self.fill_value))
            out[:, :, c] = registered
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class DynamicAlignment(Process):
    """Registration by explicit **control points** (scriptable core of manual registration).

    Where ``StarAlignment`` detects the stars automatically, this process takes supplied
    source→target correspondences (the GUI tool will enter them with the mouse), estimates the
    transformation (``similarity``/``affine``/``projective``) and resamples the image. Useful
    when the automatic path fails: few stars, mosaics, non-stellar fields.

    Points in **pixels**, flat lists ``[x0, y0, x1, y1, …]``. ``reference`` (view id, optional)
    fixes the output geometry; otherwise we keep that of the source image.
    """

    process_id = "DynamicAlignment"
    category = "ImageRegistration"
    supports_realtime = False  # geometry of the reference
    is_maskable = False
    parameters = [
        Parameter("source", "floatlist", default=[], label=N_("Source points [x,y,…]")),
        Parameter("target", "floatlist", default=[], label=N_("Target points [x,y,…]")),
        Parameter("mode", "enum", "affine",
                  choices=("similarity", "affine", "projective"), label=N_("Transformation")),
        Parameter("reference", "str", "", label=N_("Reference view (output geometry)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from skimage.transform import estimate_transform, warp

        src = np.asarray(self.source, dtype=np.float64).reshape(-1, 2)
        dst = np.asarray(self.target, dtype=np.float64).reshape(-1, 2)
        if len(src) < 2 or len(src) != len(dst):
            raise ValueError(
                _t("DynamicAlignment: at least 2 equal source/target point pairs are required."))

        out_shape = data.shape[:2]
        if self.reference:
            from ..process import context

            ref = context.resolve_image_full(self.reference)
            if ref is not None:
                out_shape = ref.shape[:2]

        tform = estimate_transform(self.mode, src, dst)  # source → target
        out = np.empty((out_shape[0], out_shape[1], data.shape[2]), dtype=np.float32)
        for c in range(data.shape[2]):
            out[:, :, c] = warp(data[:, :, c], tform.inverse, output_shape=out_shape,
                                order=1, mode="constant", cval=0.0)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class PhaseCorrelationAlignment(Process):
    """Subpixel registration by phase correlation — **without stars** (skimage + scipy).

    Estimates the global offset (translation) between the view and its reference via
    ``phase_cross_correlation`` (accuracy ``1/upsample`` pixel), then translates each channel.
    Ideal in planetary / lucky imaging where ``StarAlignment`` has no stellar landmarks.
    """

    process_id = "PhaseCorrelationAlignment"
    category = "ImageRegistration"
    supports_realtime = False  # geometry of the reference
    is_maskable = False
    parameters = [
        Parameter("reference_id", "str", "", label=N_("Reference view (id)")),
        Parameter("reference_path", "path", "", label=N_("…or reference file")),
        Parameter("upsample", "int", 10, 1, 100, label=N_("Subpixel factor")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from scipy.ndimage import shift as ndi_shift
        from skimage.registration import phase_cross_correlation

        ref = _resolve_reference(self.reference_id, self.reference_path)
        ref_lum = ref.mean(axis=2)
        src_lum = data.mean(axis=2)
        offset, _, _ = phase_cross_correlation(
            ref_lum, src_lum, upsample_factor=int(self.upsample)
        )
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            out[:, :, c] = ndi_shift(data[:, :, c], offset, order=1,
                                     mode="constant", cval=0.0)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class FeatureAlignment(Process):
    """Robust registration by ORB descriptor matching (OpenCV) — without a catalog.

    Detects ORB keypoints in the view and its reference, matches the descriptors, estimates a
    homography by RANSAC and resamples. Works on non-stellar fields (landscape, terrestrial
    mosaics) where ``StarAlignment`` does not apply.
    """

    process_id = "FeatureAlignment"
    category = "ImageRegistration"
    supports_realtime = False  # geometry of the reference
    is_maskable = False
    parameters = [
        Parameter("reference_id", "str", "", label=N_("Reference view (id)")),
        Parameter("reference_path", "path", "", label=N_("…or reference file")),
        Parameter("max_features", "int", 2000, 50, 20000, label=N_("Max ORB points")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import cv2

        ref = _resolve_reference(self.reference_id, self.reference_path)
        ref_u8 = np.clip(ref.mean(axis=2) * 255.0, 0, 255).astype(np.uint8)
        src_u8 = np.clip(data.mean(axis=2) * 255.0, 0, 255).astype(np.uint8)

        orb = cv2.ORB_create(int(self.max_features))
        kp1, des1 = orb.detectAndCompute(src_u8, None)
        kp2, des2 = orb.detectAndCompute(ref_u8, None)
        if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
            raise ValueError(_t("FeatureAlignment: not enough matchable ORB keypoints."))

        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = sorted(matcher.match(des1, des2), key=lambda m: m.distance)
        if len(matches) < 4:
            raise ValueError(_t("FeatureAlignment: fewer than 4 matches."))
        src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        homography, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        if homography is None:
            raise ValueError(_t("FeatureAlignment: homography could not be estimated."))

        h, w = ref.shape[:2]
        out = np.empty((h, w, data.shape[2]), dtype=np.float32)
        for c in range(data.shape[2]):
            out[:, :, c] = cv2.warpPerspective(data[:, :, c], homography, (w, h),
                                               flags=cv2.INTER_LINEAR)
        return np.clip(out, 0.0, 1.0).astype(np.float32)
