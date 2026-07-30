"""LocalNormalization — normalizes a frame onto a reference before integration.

Aligns the background (low-frequency component) and the scale of each frame onto a common
reference → integration rejects outliers better and avoids gradient artifacts. Pragmatic
version: low-frequency additive field + global multiplicative gain (least squares). Pure
scipy/numpy.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class LocalNormalization(Process):
    process_id = "LocalNormalization"
    category = "Calibration"
    supports_realtime = False  # reference of fixed size
    parameters = [
        Parameter("reference", "str", "", label=N_("Reference view")),
        Parameter("reference_path", "path", "", label=N_("…or reference file")),
        Parameter("scale", "real", 128.0, 4.0, 1024.0, label=N_("Background scale (σ)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if not self.reference and not self.reference_path:
            # no reference requested: the normalization has nothing to do
            return data.copy()
        from scipy.ndimage import gaussian_filter

        from .registration import _resolve_reference

        # A reference that is requested but not found is an error, not a no-op: in a
        # pipeline, returning the image unchanged would produce a silently unnormalized
        # integration, undetectable in the result.
        ref = _resolve_reference(self.reference, self.reference_path)
        sigma = float(self.scale)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            rc = ref[:, :, min(c, ref.shape[2] - 1)]
            dc = data[:, :, c]
            bg_d = gaussian_filter(dc, sigma=sigma, mode="reflect")
            bg_r = gaussian_filter(rc, sigma=sigma, mode="reflect")
            # robust multiplicative gain (ratio of the spreads around the background)
            hp_d = dc - bg_d
            hp_r = rc - bg_r
            denom = float(np.std(hp_d)) or 1e-6
            gain = float(np.std(hp_r)) / denom
            out[:, :, c] = hp_d * gain + bg_r  # rescaled scale + background of the reference
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class DrizzleIntegration(Process):
    """Drizzle — reconstruction on an oversampled grid from *dithered* exposures.

    Drizzle does not consist in enlarging already registered images: it is the opposite. It
    takes the **unregistered** exposures, knows the geometric transformation of each one onto
    the output grid, and deposits every pixel there after having **shrunk** it by a factor
    ``pixfrac``. It is that shrinking, combined with the fact that the exposures do not fall in
    the same place (the dithering), which restores detail below the sampling step.

    Registering first, as the previous implementation did, destroys precisely the information
    that drizzle exploits: the interpolation of the registration has already mixed the
    subpixels. Hence the reference parameters — drizzle estimates the transformations itself,
    or receives them.

    # Implementation

    Each output pixel is sampled ``supersample²`` times; each sample is brought back into the
    frame of the exposure by the inverse transformation, and counts if and only if it falls
    within the *drop* of the nearest input pixel (a square of side ``pixfrac`` centered on that
    pixel). This sampling formulation handles rotation exactly, where an overlap computation
    separable in x and y would only be right under translation. The cost is ``supersample²``
    interpolations per output pixel and per exposure; ``supersample=3`` is enough in practice.

    The accumulated weight is put to use: where no exposure has contributed (edges, areas
    masked by the dithering), the output is zero rather than an invented value.
    """

    process_id = "DrizzleIntegration"
    category = "ImageIntegration"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("Frames (unregistered)")),
        Parameter("scale", "int", 2, 1, 4, label=N_("Upsampling")),
        Parameter("pixfrac", "real", 1.0, 0.01, 1.0, label=N_("Pixel fraction")),
        Parameter("supersample", "int", 3, 1, 8, label=N_("Samples per pixel"),
                  tooltip=N_("Accuracy of the overlap computation; 3 is enough in practice")),
        Parameter("reference_id", "str", "", label=N_("Reference view (id)")),
        Parameter("reference_path", "path", "", label=N_("…or reference file")),
        Parameter("transforms", "floatlist", [], label=N_("Transforms (6 per frame)"),
                  tooltip=N_("Affine matrices a,b,c,d,e,f; empty = estimated from stars")),
        Parameter("new_image_id", "str", "drizzle", label=N_("Result id")),
    ]

    # --- transformations --------------------------------------------------------
    def _explicit_transforms(self, count: int) -> list[np.ndarray] | None:
        if not self.transforms:
            return None
        if len(self.transforms) != 6 * count:
            raise ValueError(
                _t("DrizzleIntegration: {n} values for {count} frames "
                   "(6 per frame required)").format(n=len(self.transforms), count=count))
        plates = np.asarray(self.transforms, dtype=np.float64).reshape(count, 2, 3)
        return [np.vstack([m, [0.0, 0.0, 1.0]]) for m in plates]

    def _estimate(self, frame: np.ndarray, reference: np.ndarray) -> np.ndarray:
        """Transformation frame → reference, estimated on the stars."""
        import astroalign

        transform, _ = astroalign.find_transform(frame.mean(axis=2), reference.mean(axis=2))
        return np.asarray(transform.params, dtype=np.float64)

    def _reference(self) -> np.ndarray | None:
        if not self.reference_id and not self.reference_path:
            return None
        from .registration import _resolve_reference

        return _resolve_reference(self.reference_id, self.reference_path)

    # --- kernel -----------------------------------------------------------------
    def _drop(self, frame: np.ndarray, matrix: np.ndarray, shape: tuple[int, int],
              acc: np.ndarray, weights: np.ndarray) -> None:
        """Deposits an exposure onto the output grid, accumulating values and weights."""
        from scipy.ndimage import map_coordinates

        s = int(self.scale)
        ss = int(self.supersample)
        half = float(self.pixfrac) / 2.0
        height, width = shape
        inverse = np.linalg.inv(matrix)

        # centers of the subsamples, in output grid coordinates
        offsets = (np.arange(ss, dtype=np.float64) + 0.5) / ss - 0.5
        ys_out = (np.arange(height, dtype=np.float64)[:, None] + 0.5)
        xs_out = (np.arange(width, dtype=np.float64)[None, :] + 0.5)

        for dy in offsets:
            for dx in offsets:
                # output → frame of the reference (division by the oversampling)
                yr = (ys_out + dy) / s - 0.5
                xr = (xs_out + dx) / s - 0.5
                # reference → frame of the exposure
                xf = inverse[0, 0] * xr + inverse[0, 1] * yr + inverse[0, 2]
                yf = inverse[1, 0] * xr + inverse[1, 1] * yr + inverse[1, 2]
                xf = np.broadcast_to(xf, (height, width))
                yf = np.broadcast_to(yf, (height, width))

                # The sample counts if it falls within the shrunk drop of an existing input
                # pixel. The domain runs from −0.5 to N−0.5: the drop of pixel 0 extends half
                # a pixel beyond its center, and excluding it would cut half a row off the
                # coverage all around the border.
                inside = ((np.abs(xf - np.round(xf)) <= half)
                          & (np.abs(yf - np.round(yf)) <= half)
                          & (xf >= -0.5) & (xf <= frame.shape[1] - 0.5)
                          & (yf >= -0.5) & (yf <= frame.shape[0] - 0.5))
                if not inside.any():
                    continue
                coords = np.stack([yf[inside], xf[inside]])
                for c in range(frame.shape[2]):
                    acc[:, :, c][inside] += map_coordinates(
                        frame[:, :, c], coords, order=1, mode="nearest")
                weights[inside] += 1.0

    def combine(self) -> np.ndarray:
        from ..io import load_image_array

        if not self.frames:
            raise ValueError(_t("DrizzleIntegration: no frames provided"))
        s = int(self.scale)
        explicites = self._explicit_transforms(len(self.frames))
        reference = self._reference()

        first = load_image_array(self.frames[0]).astype(np.float32)
        model = reference if reference is not None else first
        height, width = model.shape[0] * s, model.shape[1] * s
        channels = first.shape[2]
        acc = np.zeros((height, width, channels), dtype=np.float64)
        weights = np.zeros((height, width), dtype=np.float64)

        for index, path in enumerate(self.frames):
            self._progress(index / len(self.frames),
                           f"Drizzle {index + 1}/{len(self.frames)}")
            frame = (first if index == 0
                     else load_image_array(path).astype(np.float32))
            if explicites is not None:
                matrix = explicites[index]
            elif reference is not None:
                matrix = self._estimate(frame, reference)
            else:
                # No reference: the exposures are assumed to be already superimposed. Drizzle
                # then reduces to a clean resampling — and we say so, rather than letting one
                # believe in a subpixel reconstruction that did not take place.
                matrix = np.eye(3)
            self._drop(frame, matrix, (height, width), acc, weights)

        self._progress(1.0, "Drizzle")
        coverage = weights[:, :, None]
        return np.where(coverage > 0, acc / np.maximum(coverage, 1e-9),
                        0.0).astype(np.float32)

    def execute_global(self, app) -> bool:
        from ..model.image import Image

        app.new_window(Image(self.combine()), window_id=self.new_image_id or None)
        return True
