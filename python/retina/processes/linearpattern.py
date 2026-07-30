"""Linear patterns — columns and rows that are not in the sky.

Many CMOS sensors exhibit **banding**: columns (or rows) whose level departs from their
neighbors by a few ADU. On a single exposure it is invisible; on a hundred stacked exposures
it survives integration — the pattern is fixed, so it adds up while the noise averages out.
This is the **LPS** (linear pattern subtraction) step, and our pipeline did not have it.

# The measurement

For each column we take the **median** of its pixels. The median of a column of an astronomical
image is the sky background at that place: stars and nebulae weigh nothing there, being a
minority. What remains is to separate, within that sequence of medians, what varies slowly —
the real background gradient, which must under no circumstances be touched — from what jumps
from one column to the next, which is the pattern. A median filter along the axis makes that
split.

# The CFA trap

On an **undebayered** image, every other column sees a different filter. Their medians have no
reason to be equal, and correcting that difference would amount to erasing the mosaic — that
is, the color information. Hence the ``cfa`` mode, which works on the four sub-planes
separately. It is also why LPS belongs **before** the debayer: afterwards, the pattern has been
mixed between colors by the interpolation and is no longer separable.
"""

from __future__ import annotations

import json
import os

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register

#: tag of the overlays laid down by :class:`LinearDefectDetection`
DEFECTS_TAG = "linear-defects"

#: width of the median filter that separates the slow gradient from the pattern. Eleven is
#: measured, not chosen: it is the window that leaves the smallest residual where there is no
#: defect (99th percentile at 0.0007 against 0.0021 at sixty-three), while leaving defects of
#: three consecutive columns intact. Wider, the trend follows poorly and the residual noise
#: climbs.
TREND_WINDOW = 11


def _plans(data: np.ndarray, cfa: bool) -> list[tuple[tuple, np.ndarray]]:
    """The planes to process, with the slicing that allows them to be put back together.

    In CFA mode these are the four sub-mosaics; otherwise, the channels of the image.
    """
    if cfa:
        h = (data.shape[0] // 2) * 2
        w = (data.shape[1] // 2) * 2
        return [((slice(dy, h, 2), slice(dx, w, 2), 0), data[dy:h:2, dx:w:2, 0])
                for dy in (0, 1) for dx in (0, 1)]
    return [((slice(None), slice(None), c), data[:, :, c]) for c in range(data.shape[2])]


def _offsets(plan: np.ndarray, axis: int) -> np.ndarray:
    """Deviation of each column (``axis=0``) or row (``axis=1``) from the local trend.

    ``axis`` denotes the axis along which we take the **median**: for a column pattern, we
    take the median over the rows, hence ``axis=0``.

    No clipping of the deviations, and that is deliberate: a first attempt rejected deviations
    exceeding *k* spreads, to guard against a satellite trail. What it discarded was in fact
    exactly the defects to be corrected — which are, by construction, the largest deviations of
    the distribution. The process no longer did anything. The protection against an aligned
    structure is elsewhere: in the **median** of the column, which a trail crossing a few pixels
    does not move, and in the ``defect_list`` mode for whoever wants to be conservative.
    """
    from scipy.ndimage import median_filter

    medians = np.median(plan, axis=axis)
    window = min(TREND_WINDOW, max(len(medians) // 4 * 2 + 1, 3))
    trend = median_filter(medians, size=window, mode="reflect")
    return medians - trend


def detect_linear_defects(data: np.ndarray, *, columns: bool = True, rows: bool = False,
                          threshold_sigma: float = 3.0, cfa: bool = False) -> list[dict]:
    """Columns and rows whose level departs significantly from their neighbors.

    Returns a list of ``{axis, index, offset, sigma}`` — ``axis`` being ``'column'`` or
    ``'row'``, ``index`` the position in the **whole** image (and not in the CFA sub-plane).
    """
    defects = []
    for slice_region, plan in _plans(np.asarray(data, dtype=np.float64), cfa):
        if plan.ndim != 2 or min(plan.shape) < 8:
            continue
        for active, axis, name in ((columns, 0, "column"), (rows, 1, "row")):
            if not active:
                continue
            deviations = _offsets(plan, axis)
            sigma = 1.4826 * float(np.median(np.abs(deviations - np.median(deviations))))
            if sigma <= 0.0:
                continue
            pas = 2 if cfa else 1
            start = slice_region[1 - axis].start or 0 if cfa else 0
            for i in np.where(np.abs(deviations) > threshold_sigma * sigma)[0]:
                defects.append({
                    "axis": name,
                    "index": int(i) * pas + start,
                    "offset": float(deviations[i]),
                    "sigma": float(abs(deviations[i]) / sigma),
                })
    defects.sort(key=lambda d: (d["axis"], d["index"]))
    return defects


@register
class LinearDefectDetection(Process):
    """Locates defective columns and rows. Read-only.

    Serves two purposes: seeing the pattern (the overlays draw it), and producing the list that
    :class:`LinearPatternSubtraction` will correct — in the pipeline, this list is measured once
    on the master flat and reused for every exposure.
    """

    process_id = "LinearDefectDetection"
    category = "ImageInspection"
    supports_realtime = False
    parameters = [
        Parameter("columns", "bool", True, label=N_("Detect columns")),
        Parameter("rows", "bool", False, label=N_("Detect rows")),
        Parameter("threshold_sigma", "real", 5.0, 1.0, 50.0, label=N_("Threshold (σ)")),
        Parameter("cfa", "bool", False, label=N_("Undebayered CFA image")),
        Parameter("output_path", "path", "", label=N_("Export defect list (JSON)")),
        Parameter("show_defects", "bool", True, label=N_("Draw defects")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    def measure(self, image) -> dict:
        data = image.data if hasattr(image, "data") else np.asarray(image)
        defects = detect_linear_defects(
            data, columns=bool(self.columns), rows=bool(self.rows),
            threshold_sigma=float(self.threshold_sigma), cfa=bool(self.cfa))
        self.result = {
            "n_defects": len(defects), "defects": defects,
            "width": int(data.shape[1]), "height": int(data.shape[0]),
        }
        if self.output_path:
            self.result["output_path"] = self.export(str(self.output_path))
        return self.result

    def export(self, path: str) -> str:
        if not self.result:
            raise ValueError(_t("LinearDefectDetection: run the measurement first."))
        target = os.path.abspath(os.path.expanduser(path))
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as flux:
            json.dump({"version": 1, "defects": self.result["defects"]}, flux, indent=1)
        return target

    def overlays(self) -> list[dict]:
        if not self.result or not self.result["defects"]:
            return []
        height, width = self.result["height"], self.result["width"]
        segments = []
        for default in self.result["defects"]:
            i = default["index"] + 0.5
            segments.append([(i, 0.0), (i, float(height))] if default["axis"] == "column"
                            else [(0.0, i), (float(width), i)])
        return [{"kind": "lines", "color": (1.0, 0.4, 0.3, 0.8), "width": 1.0,
                 "segments": segments}]

    def execute_on(self, view) -> bool:  # read-only
        self.measure(view.image)
        if self.show_defects and view.window is not None:
            view.window.viewport.set_overlays(DEFECTS_TAG, self.overlays())
        return True

    def execute_on_image(self, image):
        self.measure(image)
        return image


@register
class LinearPatternSubtraction(Process):
    """Removes the column or row pattern — the **LPS** step.

    Two modes:

    - ``auto`` (default): each column is brought back onto the trend of its neighbors. Nothing
      to measure in advance, nothing to carry over between exposures.
    - ``defect_list``: only the columns listed in a JSON produced by
      :class:`LinearDefectDetection` are corrected. More conservative, and that is what we want
      in a pipeline — the pattern is a property of the **sensor**, measured once.

    The background gradient is never touched: we only correct the deviation of each column from
    the **local trend** of its neighbors, obtained by median filter. A real gradient varies
    slowly, so it sits in the trend and not in the deviation.
    """

    process_id = "LinearPatternSubtraction"
    category = "CosmeticCorrection"
    parameters = [
        Parameter("columns", "bool", True, label=N_("Correct columns")),
        Parameter("rows", "bool", False, label=N_("Correct rows")),
        Parameter("mode", "enum", "auto", choices=("auto", "defect_list"), label=N_("Mode")),
        Parameter("defects_path", "path", "", label=N_("Defect list (JSON)")),
        Parameter("cfa", "bool", False, label=N_("Undebayered CFA image")),
    ]

    def _defect_list(self) -> dict[str, set[int]] | None:
        if self.mode != "defect_list":
            return None
        if not self.defects_path:
            raise ValueError(_t(
                "LinearPatternSubtraction(mode='defect_list'): 'defects_path' parameter "
                "required (the JSON produced by LinearDefectDetection)."))
        path = os.path.expanduser(str(self.defects_path))
        if not os.path.exists(path):
            raise ValueError(
                _t("LinearPatternSubtraction: defect list not found ({path})").format(
                    path=path))
        with open(path, encoding="utf-8") as flux:
            raw_data = json.load(flux)
        kept_items: dict[str, set[int]] = {"column": set(), "row": set()}
        for default in raw_data.get("defects", ()):
            axis = default.get("axis")
            if axis in kept_items:
                kept_items[axis].add(int(default["index"]))
        return kept_items

    def _apply(self, data: np.ndarray) -> np.ndarray:
        defect_list = self._defect_list()
        output = np.asarray(data, dtype=np.float64).copy()
        for slice_region, _ in _plans(output, bool(self.cfa)):
            self._checkpoint()
            plan = output[slice_region]
            for active, axis, name in ((self.columns, 0, "column"), (self.rows, 1, "row")):
                if not active:
                    continue
                deviations = _offsets(plan, axis)
                if defect_list is not None:
                    # Positions in the whole image → positions in this sub-plane.
                    pas = 2 if self.cfa else 1
                    start = (slice_region[1 - axis].start or 0) if self.cfa else 0
                    kept = np.zeros(deviations.shape, dtype=bool)
                    for index_ in defect_list[name]:
                        local = (index_ - start) // pas
                        if 0 <= local < len(kept) and (index_ - start) % pas == 0:
                            kept[local] = True
                    deviations = np.where(kept, deviations, 0.0)
                plan = plan - (deviations[None, :] if axis == 0 else deviations[:, None])
            output[slice_region] = plan
        return output.astype(np.float32)
