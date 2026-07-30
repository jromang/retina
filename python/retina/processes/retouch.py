"""Retouching: CloneStamp (scriptable) and DynamicCrop (crop + rotation).

A GUI clone-stamp tool is a mouse gesture; here we expose its **scriptable core**: copying a
disk of pixels from a source to a destination (explicit coordinates), replayable and
recordable — and, since the tool paints while dragging, a **trajectory** of points
(`CloneStamp.points`) rather than a stack of instances.
DynamicCrop combines Crop + Rotation in one pass — either by rotating the cut-out piece, or
by cutting out a tilted rectangle (cf. its ``mode`` parameter).
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class CloneStamp(Process):
    """Copies a disk of pixels (source → destination) with a softened edge.

    Coordinates in **pixels**. ``softness`` = width of the falloff at the edge (0 = hard).

    Two uses, a single core:

    - **a single stamp** — ``src_*``/``dst_*``, ``points`` empty: the historical behavior, a
      disk laid down once;
    - **a stroke** — ``points = [x0, y0, x1, y1, …]``, the successive **destination**
      positions of the gesture. The source offset is then *constant*, taken at the first
      point: ``(src_x - x0, src_y - y0)``. This is the classic semantics of a clone stamp,
      where the source follows the brush without ever changing its offset.

    A stroke is **strictly equivalent** to the stack of its individual stamps: each point
    reads the source in the image *already modified* by the preceding points (snapshot taken
    just before writing, for the case where source and destination overlap). It costs, on the
    other hand, only one history entry, which is the right granularity for a gesture: one
    wants to undo *a stroke*, not fifty disks.

    There is deliberately **no** spacing parameter: the core stamps the points it is given.
    Seeding the points along the gesture is a decision for the client, which alone knows how
    fast the mouse moved.
    """

    process_id = "CloneStamp"
    category = "Painting"
    parameters = [
        Parameter("src_x", "int", 0, 0, 1_000_000, label=N_("Source X")),
        Parameter("src_y", "int", 0, 0, 1_000_000, label=N_("Source Y")),
        Parameter("dst_x", "int", 0, 0, 1_000_000, label=N_("Destination X")),
        Parameter("dst_y", "int", 0, 0, 1_000_000, label=N_("Destination Y")),
        Parameter("radius", "int", 8, 1, 1000, label=N_("Radius")),
        Parameter("softness", "real", 0.3, 0.0, 1.0, label=N_("Softness")),
        Parameter("points", "floatlist", default=[],
                  label=N_("Stroke points [x,y,…] (destination)")),
    ]

    def _kernel(self, r: int) -> np.ndarray:
        """Alpha weights of the disk: 1 at center → 0 at edge, computed **once** per stroke."""
        dxs = np.arange(-r, r + 1)
        yy, xx = np.meshgrid(dxs, dxs, indexing="ij")
        dist = np.sqrt(xx * xx + yy * yy)
        soft = max(float(self.softness), 1e-6) * r
        return np.clip((r - dist) / soft, 0.0, 1.0)

    def _stamp(self, out: np.ndarray, alpha: np.ndarray,
               src: tuple[int, int], dst: tuple[int, int]) -> None:
        """Lays a disk down **in place** in ``out``. Clipped at the borders, no exception.

        The window retained is the intersection of the source *and* destination constraints:
        as in the historical version, a pixel whose source **or** destination falls outside
        the frame is left untouched — the disk loses a crescent rather than wrapping around
        or inventing.
        """
        h, w = out.shape[:2]
        r = (alpha.shape[0] - 1) // 2
        sx, sy = src
        dx, dy = dst
        # bounds of the (di, dj) offsets admissible for both windows at once
        i0 = max(-r, -dy, -sy)
        i1 = min(r, h - 1 - dy, h - 1 - sy)
        j0 = max(-r, -dx, -sx)
        j1 = min(r, w - 1 - dx, w - 1 - sx)
        if i0 > i1 or j0 > j1:
            return  # disk entirely out of frame: nothing to do
        a = alpha[i0 + r:i1 + r + 1, j0 + r:j1 + r + 1, None]
        dst_win = out[dy + i0:dy + i1 + 1, dx + j0:dx + j1 + 1]
        # Snapshot of the source **before** writing: source and destination may overlap, and
        # that is what makes a stroke identical to the stack of its individual stamps.
        src_win = out[sy + i0:sy + i1 + 1, sx + j0:sx + j1 + 1].copy()
        blend = (1.0 - a) * dst_win + a * src_win
        # `a == 0` must leave the pixel **untouched** (the old loop skipped those pixels):
        # a `0 * NaN` from the source would otherwise poison them at the corners of the square.
        dst_win[...] = np.where(a > 0.0, blend, dst_win)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        r = int(self.radius)
        out = data.copy()
        alpha = self._kernel(r)

        raw = list(self.points or ())
        if len(raw) % 2 != 0:
            raise ValueError(
                _t("{process_id}: points must hold an even number of values [x,y,…].").format(
                    process_id=self.process_id))
        if not raw:
            self._stamp(out, alpha, (int(self.src_x), int(self.src_y)),
                        (int(self.dst_x), int(self.dst_y)))
            return out.astype(np.float32)

        pts = [(int(round(raw[i])), int(round(raw[i + 1]))) for i in range(0, len(raw), 2)]
        off_x = int(self.src_x) - pts[0][0]
        off_y = int(self.src_y) - pts[0][1]
        for k, (px, py) in enumerate(pts):
            self._checkpoint()  # a long stroke stays cancellable
            self._stamp(out, alpha, (px + off_x, py + off_y), (px, py))
            if len(pts) > 32:
                self._progress((k + 1) / len(pts))
        return out.astype(np.float32)


@register
class Inpaint(Process):
    """Fills defects and removed stars by inpainting (OpenCV Telea/Navier-Stokes).

    The pixels to process are designated by a **mask map** (file, ≠0 = to fill in) or, if
    absent, by the pixels ≤ ``zero_threshold`` (holes left by a star removal). Fills in by
    propagating the neighboring gradients — more natural than a median.
    """

    process_id = "Inpaint"
    category = "Painting"
    parameters = [
        Parameter("mask_path", "path", "", label=N_("Mask map (≠0 = to fill in)")),
        Parameter("zero_threshold", "real", 0.0, 0.0, 1.0,
                  label=N_("Hole threshold (if no map)")),
        Parameter("radius", "int", 3, 1, 30, label=N_("Inpainting radius")),
        Parameter("method", "enum", "telea", choices=("telea", "ns"), label=N_("Method")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import cv2

        _h, _w = data.shape[:2]
        if self.mask_path:
            from ..io import load_image_array

            dmap = load_image_array(self.mask_path)
            mask = (dmap[:, :, 0] if dmap.ndim == 3 else dmap) != 0.0
        else:
            lum = data.mean(axis=2) if data.shape[2] > 1 else data[:, :, 0]
            mask = lum <= float(self.zero_threshold)
        mask_u8 = mask.astype(np.uint8) * 255
        if not mask.any():
            return data.copy()
        flag = cv2.INPAINT_TELEA if self.method == "telea" else cv2.INPAINT_NS
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            u8 = np.clip(data[:, :, c] * 255.0, 0, 255).astype(np.uint8)
            filled = cv2.inpaint(u8, mask_u8, float(self.radius), flag)
            out[:, :, c] = filled.astype(np.float32) / 255.0
        return out.astype(np.float32)


@register
class SeamlessClone(Process):
    """Clone stamp with an invisible blend (OpenCV ``seamlessClone``, Poisson).

    Copies a disk around the **source** onto the **destination** by blending the gradients
    (Poisson blending) instead of a plain alpha: the seams disappear, even on a structured
    background. Improves on ``CloneStamp`` for large areas.
    """

    process_id = "SeamlessClone"
    category = "Painting"
    parameters = [
        Parameter("src_x", "int", 0, 0, 1_000_000, label=N_("Source X")),
        Parameter("src_y", "int", 0, 0, 1_000_000, label=N_("Source Y")),
        Parameter("dst_x", "int", 0, 0, 1_000_000, label=N_("Destination X")),
        Parameter("dst_y", "int", 0, 0, 1_000_000, label=N_("Destination Y")),
        Parameter("radius", "int", 12, 2, 500, label=N_("Radius")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        import cv2

        h, w = data.shape[:2]
        r = int(self.radius)
        c_channels = data.shape[2]
        # seamlessClone works on 3 channels, 8 bits; we replicate the gray if mono
        src_rgb = data[:, :, :3] if c_channels >= 3 else np.repeat(data[:, :, :1], 3, axis=2)
        u8 = np.clip(src_rgb * 255.0, 0, 255).astype(np.uint8)

        # source patch = square window centered on the source, mask = filled disk
        sx0, sy0 = self.src_x - r, self.src_y - r
        sx1, sy1 = self.src_x + r + 1, self.src_y + r + 1
        if sx0 < 0 or sy0 < 0 or sx1 > w or sy1 > h:
            return data.copy()  # source out of bounds → no-op
        patch = u8[sy0:sy1, sx0:sx1].copy()
        ph, pw = patch.shape[:2]
        mask = np.zeros((ph, pw), np.uint8)
        cv2.circle(mask, (pw // 2, ph // 2), r, 255, -1)
        center = (int(self.dst_x), int(self.dst_y))
        if not (r <= center[0] < w - r and r <= center[1] < h - r):
            return data.copy()  # destination too close to the edge for a Poisson blend

        blended = cv2.seamlessClone(patch, u8, mask, center, cv2.NORMAL_CLONE)
        out_rgb = blended.astype(np.float32) / 255.0
        if c_channels >= 3:
            out = data.copy()
            out[:, :, :3] = out_rgb
            return out.astype(np.float32)
        return out_rgb.mean(axis=2, keepdims=True).astype(np.float32)


@register
class DynamicCrop(Process):
    """Crops a fractional ``[0,1]`` region, axis-aligned or tilted.

    Two semantics for the same angle, chosen by ``mode``:

    * ``after_crop`` (default, historical) — cuts out the axis-aligned rectangle, **then**
      rotates the piece. The canvas grows to contain everything and the corners fill with black.
    * ``rotated_rect`` — the rectangle itself is tilted: we sample the rotated grid in **one
      pass**, and the output is exactly the size of the rectangle, with no empty corner as long
      as it fits inside the image.

    The default stays ``after_crop``: a recipe, a project or an icon already saved carries no
    ``mode``, and must go on producing what it used to produce.
    """

    process_id = "DynamicCrop"
    category = "Geometry"
    is_maskable = False
    parameters = [
        Parameter("x0", "real", 0.0, 0.0, 1.0, label=N_("Left")),
        Parameter("y0", "real", 0.0, 0.0, 1.0, label=N_("Top")),
        Parameter("x1", "real", 1.0, 0.0, 1.0, label=N_("Right")),
        Parameter("y1", "real", 1.0, 0.0, 1.0, label=N_("Bottom")),
        Parameter("angle", "real", 0.0, -360.0, 360.0, label=N_("Rotation (°)")),
        Parameter("mode", "enum", "after_crop", choices=("after_crop", "rotated_rect"),
                  label=N_("Rotation mode"),
                  tooltip=N_("after_crop: rotate the cropped region, enlarging the canvas. "
                             "rotated_rect: sample a tilted rectangle, output is exactly its "
                             "size.")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        h, w = data.shape[:2]
        x0 = int(round(min(self.x0, self.x1) * w))
        x1 = max(int(round(max(self.x0, self.x1) * w)), x0 + 1)
        y0 = int(round(min(self.y0, self.y1) * h))
        y1 = max(int(round(max(self.y0, self.y1) * h)), y0 + 1)
        if self.mode == "rotated_rect":
            return self._sample_rotated(data, x0, y0, x1, y1)
        cropped = data[y0:y1, x0:x1, :]
        if abs(self.angle) < 1e-9:
            return cropped.copy()
        from scipy.ndimage import rotate

        out = rotate(cropped, angle=float(self.angle), axes=(0, 1), reshape=True,
                     order=1, mode="constant", cval=0.0)
        return np.clip(out, 0.0, 1.0).astype(np.float32)

    def _sample_rotated(self, data: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
        """Samples the **tilted** rectangle in a single pass.

        One pass and not "rotate then crop": two successive resamplings apply the blur of the
        interpolation twice, and the first would have to cover a wider area than the result so
        as not to lop off the corners.

        The output grid is built centered on the rectangle, rotated about that center, then
        read back from the source image. The direction of rotation is **that of**
        ``after_crop`` (locked down by ``tests/test_dynamic_tools.py``): a user changing mode
        must not see their image swing the other way.
        """
        from scipy.ndimage import map_coordinates

        out_w, out_h = x1 - x0, y1 - y0
        angle = np.deg2rad(float(self.angle))
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        # Local coordinates: (0, 0) at the center of the rectangle. The center is taken on the
        # **pixel centers** ((n-1)/2) and not on the edge (n/2), without which at zero angle the
        # grid would land half a pixel away from the original samples — and the two modes would
        # no longer coincide.
        u = np.arange(out_w, dtype=np.float64) - (out_w - 1) / 2.0
        v = np.arange(out_h, dtype=np.float64) - (out_h - 1) / 2.0
        uu, vv = np.meshgrid(u, v)
        cx = x0 + (out_w - 1) / 2.0
        cy = y0 + (out_h - 1) / 2.0
        xs = cx + cos_a * uu - sin_a * vv
        ys = cy + sin_a * uu + cos_a * vv
        coords = np.stack([ys, xs])  # map_coordinates reads (row, column)

        out = np.empty((out_h, out_w, data.shape[2]), dtype=np.float32)
        for c in range(data.shape[2]):
            # 2D only: interpolating across channels as well would mix the colors.
            # ``cval=0`` for whatever falls outside the image — a tilted rectangle can stick
            # out, and that is missing data, not an error. No clipping: bilinear interpolation
            # is a convex combination, it cannot exceed its inputs.
            out[:, :, c] = map_coordinates(data[:, :, c], coords, order=1,
                                           mode="constant", cval=0.0)
        return out
