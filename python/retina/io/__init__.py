"""Image I/O: FITS (astropy) and XISF (native)."""

import os

import numpy as np

from ..i18n import translate as _t
from .fits import load_fits, load_fits_header, save_fits
from .lazy import LazyImage, open_lazy

#: The only dispatch point for raster formats: adding a format here and in
#: :mod:`retina.io.raster` is enough, there is no second list anywhere else.
_RASTER_EXT = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".webp",
               ".jp2", ".j2k", ".jpx", ".j2c", ".jxl")


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


def save_image(path: str, image, keywords: dict | None = None) -> None:
    """Save an :class:`~retina.model.image.Image` according to the path's extension.

    FITS through astropy, XISF natively, TIFF/PNG/JPEG/BMP through :mod:`retina.io.raster`.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in (".fits", ".fit", ".fts"):
        save_fits(path, image, keywords)
    elif ext == ".xisf":
        from .xisf import save_xisf

        save_xisf(path, image, keywords)
    elif ext in _RASTER_EXT:
        from .raster import save_raster

        save_raster(path, image)
    else:
        raise ValueError(_t("Unsupported extension: {ext}").format(ext=ext))


__all__ = ["LazyImage", "load_fits", "load_fits_header", "load_image_array",
           "open_lazy", "save_fits", "save_image"]
