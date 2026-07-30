"""WCS-based mosaic (reproject) — **global** process.

``MosaicReproject`` loads several **plate-solved** FITS files (each carries its WCS in the
header), reprojects them onto a common grid and co-adds them
(``reproject.mosaicking.reproject_and_coadd``). This is the true astrometric mosaic: it
advantageously replaces gradient-domain blending for solved fields. Global: produces a new
window via ``app``. Lazy import.
"""

from __future__ import annotations

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class MosaicReproject(Process):
    """Reprojects + co-adds plate-solved FITS files into a mosaic (common WCS).

    Each frame must carry a valid FITS WCS. The optimal output grid (covering all the frames)
    is computed automatically. ``combine``: mean or sum of the overlaps. Global process → new
    window ``new_image_id``.
    """

    process_id = "MosaicReproject"
    category = "ImageIntegration"
    is_global = True
    parameters = [
        Parameter("frames", "pathlist", [], label=N_("FITS frames (with WCS)")),
        Parameter("combine", "enum", "mean", choices=("mean", "sum"), label=N_("Combination")),
        Parameter("new_image_id", "str", "mosaic", label=N_("Result id")),
    ]

    def combine_frames(self):
        """Returns (mosaic ``(H, W, C)`` float32, output WCS)."""
        from astropy.io import fits
        from astropy.wcs import WCS
        from reproject import reproject_interp
        from reproject.mosaicking import find_optimal_celestial_wcs, reproject_and_coadd

        if not self.frames:
            raise ValueError(_t("MosaicReproject: no frames provided"))

        arrays_wcs = []  # (data2d, WCS) for channel 0, to compute the grid
        headers = []
        cubes = []  # (C, H, W) per frame
        for path in self.frames:
            with fits.open(path) as hdul:
                hdu = next((h for h in hdul if getattr(h, "data", None) is not None), hdul[0])
                raw = np.asarray(hdu.data, dtype=np.float32)
                wcs = WCS(hdu.header).celestial
            # a 2D FITS is a single-plane cube; a 3D one is already in (C, H, W)
            cube = raw[np.newaxis, :, :] if raw.ndim == 2 else raw
            cubes.append(cube)
            headers.append(wcs)
            arrays_wcs.append((cube[0], wcs))

        out_wcs, shape_out = find_optimal_celestial_wcs(arrays_wcs)
        n_channels = max(cube.shape[0] for cube in cubes)
        combine = "mean" if self.combine == "mean" else "sum"
        planes = []
        for ci in range(n_channels):
            inputs = [
                (cube[min(ci, cube.shape[0] - 1)], wcs)
                for cube, wcs in zip(cubes, headers, strict=True)
            ]
            mosaic, _ = reproject_and_coadd(
                inputs, out_wcs, shape_out=shape_out,
                reproject_function=reproject_interp, combine_function=combine,
            )
            planes.append(np.nan_to_num(mosaic).astype(np.float32))
        return np.dstack(planes), out_wcs

    def execute_global(self, app) -> bool:
        from ..model.image import Image

        mosaic, out_wcs = self.combine_frames()
        win = app.new_window(
            Image(np.clip(mosaic, 0.0, 1.0)), window_id=self.new_image_id or None
        )
        # The output grid *is* an astrometric solution — throwing it away turned a mosaic
        # assembled by WCS into an image without WCS, which would have had to be re-solved to
        # annotate it or to look up a survey reference for it.
        win.wcs = out_wcs
        return True


@register
class MosaicPlanner(Process):
    """Computes a mosaic's pointings **before** acquiring it — the inverse of `detect_panels`.

    Everything the repository knows how to do with mosaics is *downstream*: recovering the
    panels from exposures already taken. Here we go back up the slope — a target, a sensor
    field, an overlap, and we return the list of pointings to schedule, plus a chart to check at
    a glance that the target is indeed covered.

    **Global** process: it reads no image and produces a new window (the chart), solved, hence
    superimposable on the rest.

    The tiles are laid down in the **tangent plane** of the target (`synthetic_tan`), never in
    RA/Dec arithmetic: a constant step in right ascension shrinks as cos δ, and near the pole
    the very notion of a step in RA no longer makes sense. In headless/test mode, ``set_center``
    avoids name resolution by Sesame.
    """

    process_id = "MosaicPlanner"
    category = "Astrometry"
    is_global = True
    supports_realtime = False
    parameters = [
        Parameter("target", "str", "", label=N_("Target"),
                  tooltip=N_("Object name resolved by Sesame (M31), or 'ra,dec' in degrees")),
        Parameter("reference_frame", "path", "", label=N_("Reference frame (for the field)"),
                  tooltip=N_("A FITS file whose header gives sensor size, pixel size and "
                             "focal length; otherwise set the field explicitly")),
        Parameter("fov_width", "real", 0.0, 0.0, 180.0, label=N_("Field width (deg)")),
        Parameter("fov_height", "real", 0.0, 0.0, 180.0, label=N_("Field height (deg)")),
        Parameter("tiles_x", "int", 2, 1, 20, label=N_("Tiles across")),
        Parameter("tiles_y", "int", 2, 1, 20, label=N_("Tiles down")),
        Parameter("overlap", "real", 20.0, 0.0, 90.0, label=N_("Overlap (%)")),
        Parameter("size", "int", 800, 128, 4096, label=N_("Chart size (px)")),
        Parameter("output_path", "path", "", label=N_("Export to CSV")),
        Parameter("new_image_id", "str", "", label=N_("New image id")),
    ]

    #: columns of ``.result['panels']`` and of the CSV
    COLUMNS = ("panel", "ra", "dec")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._center = None
        self.result: dict | None = None

    def set_center(self, ra: float, dec: float) -> MosaicPlanner:
        """Sets the center explicitly — bypasses name resolution (tests, offline)."""
        self._center = (float(ra), float(dec))
        return self

    def center(self) -> tuple[float, float]:
        if self._center is not None:
            return self._center
        target = str(self.target or "").strip()
        if not target:
            raise ValueError(_t("MosaicPlanner: no target given."))
        if "," in target:
            ra, _, dec = target.partition(",")
            return float(ra), float(dec)
        from astropy.coordinates import SkyCoord

        coord = SkyCoord.from_name(target)  # Sesame: network
        return float(coord.ra.deg), float(coord.dec.deg)

    def field(self) -> tuple[float, float]:
        """Field of one tile in degrees, explicit or derived from a reference header."""
        if self.fov_width > 0 and self.fov_height > 0:
            return float(self.fov_width), float(self.fov_height)
        if not self.reference_frame:
            raise ValueError(
                _t("MosaicPlanner: give fov_width/fov_height, or a reference frame."))
        from ..io.fits import load_fits_header

        header = load_fits_header(str(self.reference_frame))
        try:
            pixel_um = float(header.get("XPIXSZ", 0) or 0)
            focale_mm = float(header.get("FOCALLEN", 0) or 0)
            width_px = float(header.get("NAXIS1", 0) or 0)
            height_px = float(header.get("NAXIS2", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                _t("MosaicPlanner: cannot read the field from {path}.").format(
                    path=self.reference_frame)) from exc
        if not (pixel_um > 0 and focale_mm > 0 and width_px > 0 and height_px > 0):
            raise ValueError(
                _t("MosaicPlanner: {path} lacks XPIXSZ/FOCALLEN/NAXIS to derive the field."
                   ).format(path=self.reference_frame))
        # Scale in degrees per pixel: 206.265 arcsec/rad, then /3600.
        scale = (206.265 * pixel_um / focale_mm) / 3600.0
        return width_px * scale, height_px * scale

    def plan(self) -> list[dict]:
        """The pointings to schedule, from north-east to south-west, numbered stably."""
        from ..processes.astrometry import synthetic_tan

        ra, dec = self.center()
        fov_w, fov_h = self.field()
        nx, ny = int(self.tiles_x), int(self.tiles_y)
        rest = 1.0 - float(self.overlap) / 100.0
        pas_x, pas_y = fov_w * rest, fov_h * rest

        # Working grid large enough to contain the whole mosaic, at a convenient scale:
        # one pixel = one thousandth of the field of a tile.
        size = max(64, int(max(nx * fov_w, ny * fov_h) / (fov_w / 1000.0)))
        grid = synthetic_tan(ra, dec, size * fov_w / 1000.0, size)
        par_degre = 1000.0 / fov_w  # pixels per degree in this grid

        panels = []
        for iy in range(ny):
            for ix in range(nx):
                # Centered offsets: the mosaic is symmetric around the target.
                dx = (ix - (nx - 1) / 2.0) * pas_x * par_degre
                dy = (iy - (ny - 1) / 2.0) * pas_y * par_degre
                sky = grid.pixel_to_world(size / 2.0 + dx, size / 2.0 + dy)
                panels.append({
                    "panel": f"P{iy * nx + ix + 1:02d}",
                    "ra": float(sky.ra.deg),
                    "dec": float(sky.dec.deg),
                })
        return panels

    def export(self, path: str, panels: list[dict]) -> str:
        """CSV ``name,ra_deg,dec_deg`` — the format every planetarium knows how to import."""
        import csv
        import os

        target = os.path.abspath(os.path.expanduser(path))
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as flux:
            writer = csv.writer(flux)
            writer.writerow(["name", "ra_deg", "dec_deg"])
            for p in panels:
                writer.writerow([p["panel"], f"{p['ra']:.6f}", f"{p['dec']:.6f}"])
        return target

    def execute_global(self, app) -> bool:
        from ..model.image import Image
        from ..processes.astrometry import synthetic_tan

        panels = self.plan()
        ra, dec = self.center()
        fov_w, fov_h = self.field()
        # The chart covers the whole mosaic plus a margin: seeing the tiles glued to the edge
        # would not tell whether the target is really covered.
        rest = 1.0 - float(self.overlap) / 100.0
        span = max(fov_w * (1 + (int(self.tiles_x) - 1) * rest),
                      fov_h * (1 + (int(self.tiles_y) - 1) * rest)) * 1.3
        carte_wcs = synthetic_tan(ra, dec, span, int(self.size))
        data = self._render(carte_wcs, panels, fov_w, fov_h)

        win = app.new_window(Image(data), window_id=self.new_image_id or "MosaicPlan")
        win.wcs = carte_wcs
        self.result = {"n_panels": len(panels), "panels": panels,
                       "columns": list(self.COLUMNS),
                       "fov_width": fov_w, "fov_height": fov_h}
        if self.output_path:
            self.result["output_path"] = self.export(str(self.output_path), panels)
        return True

    def _render(self, carte_wcs, panels, fov_w: float, fov_h: float) -> np.ndarray:
        """Draws the footprint of each tile, projected — not an approximate rectangle."""
        from PIL import Image as PILImage
        from PIL import ImageDraw

        from ..processes.astrometry import synthetic_tan

        size = int(self.size)
        toile = PILImage.new("RGB", (size, size), (12, 12, 16))
        crayon = ImageDraw.Draw(toile)
        for index, panel in enumerate(panels):
            tile = synthetic_tan(panel["ra"], panel["dec"], max(fov_w, fov_h), 100)
            corners = []
            # The four corners of the tile, in *its* grid, reprojected into the chart: a tile
            # far from the center is a quadrilateral, not a rectangle, and drawing it straight
            # would suggest a coverage we do not have.
            demi_x = 50.0 * fov_w / max(fov_w, fov_h)
            demi_y = 50.0 * fov_h / max(fov_w, fov_h)
            for px, py in ((-demi_x, -demi_y), (demi_x, -demi_y),
                           (demi_x, demi_y), (-demi_x, demi_y)):
                sky = tile.pixel_to_world(50.0 + px, 50.0 + py)
                x, y = carte_wcs.world_to_pixel(sky)
                corners.append((float(x), float(y)))
            hue = (80 + (index * 37) % 120, 170, 220)
            crayon.polygon(corners, outline=hue)
            crayon.text(corners[0], panel["panel"], fill=hue)
        return np.asarray(toile, dtype=np.float32) / 255.0
