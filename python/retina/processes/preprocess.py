"""Preprocessing: CosmeticCorrection, DefectMap, Superbias, SplitCFA/MergeCFA, ExtractDualBand.

Rounds out the calibration stage. Pure numpy/scipy. ``CosmicClip`` (astroscrappy, cosmic
rays) already lives in ``cosmetic.py``; here we target static hot/cold pixels and master bias
modeling.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def _fits_slices(section: str, ndim: int) -> tuple:
    """IRAF section ``[x1:x2,y1:y2]`` → tuple of numpy slices for an ``(H, W, C)`` image.

    Three traps the convention carries within it. The **order**: FITS states x first, numpy
    the row axis — ``ccdproc`` takes care of that when both axes are given. The **omission**:
    ``[4096:4109]`` specifies only one dimension, and it is x, hence the column axis; it has
    to be padded on the left, without which we would be slicing rows. And the **channels**:
    the section addresses the geometry only, the channels follow whole — padding up to
    ``ndim`` would land the column slice on the channel axis, which is 1 in monochrome and
    would return an empty area.
    """
    from ccdproc.utils.slices import slice_from_string

    slice_region = tuple(slice_from_string(section, fits_convention=True))
    slice_region = (slice(None),) * (2 - len(slice_region)) + slice_region  # (y, x)
    return slice_region + (slice(None),) * (ndim - 2)  # channels untouched


@register
class Overscan(Process):
    """Corrects the drift of the bias level using the overscan region, then removes it.

    The overscan is a strip of pixels that are read but **never exposed**: it records the bias
    level of *that particular* frame. That is what makes it valuable — a master bias gives the
    average bias of a series, the overscan gives its value at the instant of the exposure,
    thermal drift included. On a real measured data set, the gap between the two reaches 20 %
    of the sky background: neglecting it means being off by a fifth on the very signal we are
    looking for.

    The regions are read from the header (``BIASSEC``, ``TRIMSEC``), the IRAF convention
    honored by most acquisition software. The preprocessing therefore fills them in on its
    own, rather than having them typed in by hand sensor by sensor.

    The trimming (``trim_section``) follows the correction: those columns never saw the sky,
    and keeping them would only pollute the statistics and the stretch.
    """

    process_id = "Overscan"
    category = "Calibration"
    supports_realtime = False  # changes the geometry
    is_maskable = False
    parameters = [
        Parameter("bias_section", "str", "", label=N_("Overscan region (BIASSEC)"),
                  tooltip=N_("IRAF section, e.g. [4096:4109]; empty = no correction")),
        Parameter("trim_section", "str", "", label=N_("Useful region (TRIMSEC)"),
                  tooltip=N_("IRAF section that is kept; empty = no trimming")),
        Parameter("method", "enum", "median", choices=("median", "mean"),
                  label=N_("Level estimator")),
        Parameter("axis", "enum", "auto", choices=("auto", "row", "column", "global"),
                  label=N_("Correction direction"),
                  tooltip=N_("auto: inferred from the shape of the overscan region")),
    ]

    def _levels(self, data: np.ndarray) -> np.ndarray | None:
        """Bias level measured in the overscan, ready to be broadcast over the image."""
        if not self.bias_section:
            return None
        zone = data[_fits_slices(self.bias_section, data.ndim)]
        if zone.size == 0:
            raise ValueError(
                _t("Overscan: empty region for {section!r}").format(section=self.bias_section))
        reduire = np.median if self.method == "median" else np.mean

        sens = self.axis
        if sens == "auto":
            # A strip of columns gives one level per row, and conversely. That is the useful
            # case: the read register's drift runs along the readout.
            sens = "row" if zone.shape[1] <= zone.shape[0] else "column"
        if sens == "global":
            return np.asarray(float(reduire(zone)), dtype=np.float32)
        if sens == "row":
            return reduire(zone, axis=(1, 2), keepdims=True).astype(np.float32)
        return reduire(zone, axis=(0, 2), keepdims=True).astype(np.float32)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        out = data.astype(np.float32)
        levels = self._levels(out)
        if levels is not None:
            self._progress(0.0, _t("Subtracting overscan"))
            out = out - levels
        if self.trim_section:
            self._progress(0.5, _t("Cropping to the useful area"))
            out = out[_fits_slices(self.trim_section, out.ndim)]
        return np.ascontiguousarray(out, dtype=np.float32)


@register
class CosmeticCorrection(Process):
    """Corrects hot/cold pixels by deviation from the local median (automatic detection).

    A pixel deviating by more than ``sigma`` from the 3×3 median (robust MAD scale) is
    replaced by that median. Distinct from ``CosmicClip`` (LA Cosmic model, on cosmic rays):
    here we target static sensor defects.
    """

    process_id = "CosmeticCorrection"
    category = "CosmeticCorrection"
    parameters = [
        Parameter("hot_sigma", "real", 3.0, 0.5, 20.0, label=N_("Hot pixel threshold (σ)")),
        Parameter("cold_sigma", "real", 3.0, 0.5, 20.0, label=N_("Cold pixel threshold (σ)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from scipy.ndimage import median_filter

        out = data.copy()
        for c in range(data.shape[2]):
            ch = data[:, :, c]
            med = median_filter(ch, size=3, mode="reflect")
            diff = ch - med
            scale = 1.4826 * np.median(np.abs(diff - np.median(diff))) or 1e-6
            hot = diff > self.hot_sigma * scale
            cold = diff < -self.cold_sigma * scale
            repl = hot | cold
            out[:, :, c] = np.where(repl, med, ch)
        return out.astype(np.float32)


@register
class DefectMap(Process):
    """Replaces the pixels flagged as defective (supplied map) by the local median."""

    process_id = "DefectMap"
    category = "CosmeticCorrection"
    supports_realtime = False  # fixed-size defect map
    parameters = [
        Parameter("map_path", "path", "", label=N_("Defect map (≠0 = defective)")),
        Parameter("radius", "int", 1, 1, 10, label=N_("Median radius")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from scipy.ndimage import median_filter

        if not self.map_path:
            return data.copy()
        from ..io import load_image_array

        dmap = load_image_array(self.map_path)
        defect = (dmap[:, :, 0] if dmap.ndim == 3 else dmap) != 0.0
        size = 2 * int(self.radius) + 1
        out = data.copy()
        for c in range(data.shape[2]):
            med = median_filter(data[:, :, c], size=size, mode="reflect")
            out[:, :, c] = np.where(defect, med, data[:, :, c])
        return out.astype(np.float32)


@register
class PixelInterpolation(Process):
    """Fills NaN / dead pixels by convolution (astropy ``interpolate_replace_nans``).

    Each NaN is replaced by the Gaussian-weighted mean of its valid neighborhood. Complements
    ``DefectMap``: if ``threshold > 0``, the pixels **exactly** at 0 (or negative) are first
    flagged dead (set to NaN) before interpolation.
    """

    process_id = "PixelInterpolation"
    category = "CosmeticCorrection"
    parameters = [
        Parameter("sigma", "real", 2.0, 0.3, 20.0, label=N_("Convolution radius (σ)")),
        Parameter("mark_zeros", "bool", False, label=N_("Treat pixels ≤0 as dead")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from astropy.convolution import Gaussian2DKernel, interpolate_replace_nans

        kernel = Gaussian2DKernel(x_stddev=float(self.sigma))
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            ch = data[:, :, c].astype(np.float64)
            if self.mark_zeros:
                ch = np.where(ch <= 0.0, np.nan, ch)
            if np.isnan(ch).any():
                ch = interpolate_replace_nans(ch, kernel)
            out[:, :, c] = np.nan_to_num(ch)
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class Superbias(Process):
    """Models a master bias: keeps the large-scale structure, removes the noise.

    Starlet decomposition; we zero out the first ``noise_layers`` detail layers
    (high-frequency noise) and reconstruct → a smooth, noise-free "superbias".
    Reuses ``starlet_transform`` (multiscale).
    """

    process_id = "Superbias"
    category = "Calibration"
    parameters = [
        Parameter("noise_layers", "int", 6, 1, 12, label=N_("Noise layers removed")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        from .multiscale import starlet_transform

        n = int(self.noise_layers)
        out = np.empty_like(data)
        for c in range(data.shape[2]):
            _details, residual = starlet_transform(data[:, :, c], n)
            out[:, :, c] = residual  # keeps the large-scale structure only
        return np.clip(out, 0.0, 1.0).astype(np.float32)


@register
class SplitCFA(Process):
    """Splits a CFA (Bayer) matrix into 4 half-resolution sub-planes stacked as channels.

    Headless contract: output ``(H/2, W/2, 4)`` = CFA planes 0..3 (positions 00,01,10,11).
    ``MergeCFA`` does the inverse. Useful to calibrate or denoise each CFA site separately.
    """

    process_id = "SplitCFA"
    category = "Calibration"
    is_maskable = False
    parameters = []

    def _apply(self, data: np.ndarray) -> np.ndarray:
        ch = data[:, :, 0]
        h, w = (ch.shape[0] // 2) * 2, (ch.shape[1] // 2) * 2
        ch = ch[:h, :w]
        planes = [ch[0::2, 0::2], ch[0::2, 1::2], ch[1::2, 0::2], ch[1::2, 1::2]]
        return np.dstack(planes).astype(np.float32)


@register
class ExtractDualBand(Process):
    """Extracts Ha or OIII from an OSC raw taken under a dual-band filter, by superpixel.

    On a color sensor behind an Ha/OIII filter (Seestar, Dwarf, OSC + L-eXtreme…),
    demosaicing to RGB **mixes two lines that have nothing to do with each other**: the
    ``Debayer`` interpolation smears the Hα signal (656 nm, captured by the red photosites
    alone) onto the greens, and conversely. We therefore prefer to decimate: each 2×2 block of
    the pattern gives one output pixel, without any interpolation.

    - **Ha** = the **R** site of the block — at 656 nm, only the red filter transmits.
    - **OIII** = the **mean of the two G sites** — the 500 nm line is captured by the greens,
      and averaging the two planes divides the noise by √2 without costing any resolution (the
      two greens are co-located at the scale of the block).

    The **B** site is ignored: under a dual-band filter it sees neither of the two useful
    lines (some OIII does get through, but with a very different efficiency and background —
    adding it would degrade the measurement instead of improving it).

    Output ``(H/2, W/2, 1)`` — a **monochrome** image, processable afterwards like an ordinary
    narrowband one (integration, stretch, then HOO/SHO composition as desired).
    """

    process_id = "ExtractDualBand"
    category = "Calibration"
    supports_realtime = False  # changes the geometry (half resolution) and the channel count
    is_maskable = False
    parameters = [
        Parameter("pattern", "enum", "RGGB",
                  choices=("RGGB", "BGGR", "GRBG", "GBRG"), label=N_("CFA pattern")),
        Parameter("band", "enum", "ha", choices=("ha", "oiii"), label=N_("Emission band"),
                  tooltip=N_("ha: red site (656 nm); oiii: mean of the two green sites (500 nm)")),
    ]

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] != 1:
            raise ValueError(
                _t("ExtractDualBand: a raw single-channel CFA image is required, "
                   "but this one has {channels} channels. Apply it before Debayer.")
                .format(channels=data.shape[2])
            )
        ch = data[:, :, 0]
        h, w = (ch.shape[0] // 2) * 2, (ch.shape[1] // 2) * 2
        ch = ch[:h, :w]
        # The 4 letters of the pattern describe the 2×2 block in the order
        # (0,0), (0,1), (1,0), (1,1).
        planes = {}
        for index, lettre in enumerate(self.pattern):
            planes.setdefault(lettre, []).append(ch[index // 2 :: 2, index % 2 :: 2])
        if self.band == "ha":
            out = planes["R"][0].astype(np.float32)
        else:
            verts = planes["G"]
            out = ((verts[0].astype(np.float32) + verts[1].astype(np.float32)) * 0.5)
        return np.ascontiguousarray(out[:, :, None], dtype=np.float32)


@register
class MergeCFA(Process):
    """Recomposes a full-resolution CFA mosaic from 4 planes (inverse of SplitCFA)."""

    process_id = "MergeCFA"
    category = "Calibration"
    is_maskable = False
    parameters = []

    def _apply(self, data: np.ndarray) -> np.ndarray:
        if data.shape[2] < 4:
            return data.copy()
        p = [data[:, :, i] for i in range(4)]
        h, w = p[0].shape
        out = np.zeros((h * 2, w * 2), dtype=np.float32)
        out[0::2, 0::2], out[0::2, 1::2] = p[0], p[1]
        out[1::2, 0::2], out[1::2, 1::2] = p[2], p[3]
        return out[:, :, None]
