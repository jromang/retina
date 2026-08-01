"""Image I/O: FITS (astropy) and XISF (native)."""

import os

import numpy as np

from ..i18n import translate as _t
from .fits import load_fits, load_fits_header, save_fits
from .lazy import LazyImage, open_lazy

#: Containers that carry the linear data as it is: full float precision, keywords, WCS.
ASTRO_EXT = (".fits", ".fit", ".fts", ".xisf")
#: Raster formats that keep 32-bit float. Exchange with retouching software without loss.
FLOAT_RASTER_EXT = (".tif", ".tiff")
#: Raster formats that quantize to 8 or 16 bits. **Writing a linear image into one of these
#: gives a black picture**, since a linear sky background sits around 1e-3: the caller is
#: expected to stretch first, and the interface warns before it happens. Grouped here rather
#: than guessed from the extension in the frontend, which would be a second list.
BYTE_RASTER_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp",
                   ".jp2", ".j2k", ".jpx", ".j2c", ".jxl")
#: The only dispatch point for raster formats: adding a format here and in
#: :mod:`retina.io.raster` is enough, there is no second list anywhere else.
_RASTER_EXT = FLOAT_RASTER_EXT + BYTE_RASTER_EXT


def load_image_array(path: str) -> np.ndarray:
    """Load an image file (FITS/XISF/TIFF/PNG/JPEG/BMP) → ``(H, W, C)`` float32 array."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fits", ".fit", ".fts"):
        return load_fits(path)[0].data
    if ext == ".xisf":
        from .xisf import load_xisf

        return load_xisf(path)[0].data
    if ext in _RASTER_EXT:
        from .raster import load_raster

        return load_raster(path)
    from .raw import RAW_EXT, load_raw

    if ext in RAW_EXT:
        return load_raw(path)
    raise ValueError(_t("Unsupported extension: {ext}").format(ext=ext))


def save_image(path: str, image, keywords: dict | None = None, stf=None) -> None:
    """Save an :class:`~retina.model.image.Image` according to the path's extension.

    FITS through astropy, XISF natively, TIFF/PNG/JPEG/BMP through :mod:`retina.io.raster`.
    ``stf`` is the screen transfer function to record in the file; XISF is the only format
    that carries one, and the others ignore it.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fits", ".fit", ".fts"):
        save_fits(path, image, keywords)
    elif ext == ".xisf":
        from .xisf import save_xisf

        save_xisf(path, image, keywords, stf=stf)
    elif ext in _RASTER_EXT:
        from .raster import save_raster

        save_raster(path, image)
    else:
        raise ValueError(_t("Unsupported extension: {ext}").format(ext=ext))


def is_byte_format(path: str) -> bool:
    """True if writing this path quantizes to 8 or 16 bits — see :data:`BYTE_RASTER_EXT`."""
    return os.path.splitext(path)[1].lower() in BYTE_RASTER_EXT


def format_groups() -> dict[str, list[str]]:
    """Extensions the application reads and writes, by group, without the leading dot.

    Serves the file dialogs and the 8-bit warning of the interface. Published rather than
    mirrored by hand, so that adding a format stays a one-line change in this module.
    """
    from .raw import RAW_EXT

    return {
        "astro": [e[1:] for e in ASTRO_EXT],
        "float_raster": [e[1:] for e in FLOAT_RASTER_EXT],
        "byte_raster": [e[1:] for e in BYTE_RASTER_EXT],
        # Camera RAW is read-only: rawpy demosaics, it does not write back.
        "raw": sorted(e[1:] for e in RAW_EXT),
    }


__all__ = ["ASTRO_EXT", "BYTE_RASTER_EXT", "FLOAT_RASTER_EXT", "LazyImage", "format_groups",
           "is_byte_format", "load_fits", "load_fits_header", "load_image_array", "open_lazy",
           "save_fits", "save_image"]
