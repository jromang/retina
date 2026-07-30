"""I/O for common raster images: TIFF (32-bit float), PNG/JPEG/BMP/WebP (8-bit),
JPEG2000, JPEG XL.

Complements FITS/XISF for **exchange** with retouching software and for sharing. TIFF
through ``tifffile`` (preserves 32-bit float); PNG/JPEG/BMP/WebP through ``imageio`` (8-bit
encoding, data assumed already stretched to ``[0,1]``). JPEG2000 through Pillow (OpenJPEG,
lossless wavelet compression): **16-bit** in grayscale, 8-bit in color (a plugin limit).
JPEG XL through ``pillow-jxl-plugin``.

**All of them remain interop formats, and that is a choice.** JPEG XL can carry float and
would compress better than TIFF — but the astro ecosystem does not read it, whereas XISF is
read by the reference suites and TIFF by everyone. Writing float into it would make an
archive file nobody could reopen: to archive, XISF; to edit elsewhere, TIFF; to share, this
module.

Lossy formats are written **losslessly when they know how** (WebP, JPEG2000, JPEG XL):
recompressing an already-processed astronomical image to save bytes would be a bad trade.
"""

from __future__ import annotations

import os

import numpy as np

from ..i18n import translate as _t
from ..model.image import Image

_FLOAT_EXT = {".tif", ".tiff"}
_BYTE_EXT = {".png", ".jpg", ".jpeg", ".bmp"}
#: WebP has its own group despite being 8-bit: it carries alpha (unlike JPEG) and wants
#: ``lossless=True`` on write, which the generic ``imageio`` path would not pass through.
_WEBP_EXT = {".webp"}
_JP2_EXT = {".jp2", ".j2k", ".jpx", ".j2c"}
_JXL_EXT = {".jxl"}


def _to_hwc(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        return arr[:, :, np.newaxis]
    return arr


def load_raster(path: str) -> np.ndarray:
    """Load TIFF/PNG/JPEG/BMP → ``(H, W, C)`` float32 array in ``[0, 1]``."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _FLOAT_EXT:
        import tifffile

        arr = np.asarray(tifffile.imread(path), dtype=np.float32)
    elif ext in _BYTE_EXT:
        import imageio.v3 as iio

        raw = np.asarray(iio.imread(path))
        arr = raw.astype(np.float32)
        if np.issubdtype(raw.dtype, np.integer):
            arr /= float(np.iinfo(raw.dtype).max)
    elif ext in _JP2_EXT | _WEBP_EXT | _JXL_EXT:
        if ext in _JXL_EXT:
            _load_jxl_plugin()
        from PIL import Image as PImage

        raw = np.asarray(PImage.open(path))
        arr = raw.astype(np.float32)
        if np.issubdtype(raw.dtype, np.integer):
            arr /= float(np.iinfo(raw.dtype).max)
    else:
        raise ValueError(_t("Unsupported raster extension: {ext}").format(ext=ext))
    return np.ascontiguousarray(_to_hwc(arr))


def _load_jxl_plugin() -> None:
    """Register the JPEG XL codec with Pillow, or say how to install it.

    The import has a **side effect** — it installs the plugin — hence the imported variable
    going unused. Without it, Pillow does not know the extension and would return an obscure
    error; here the user reads what they have to do.
    """
    try:
        import pillow_jxl  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            _t("JPEG XL requires the 'astro' extra — pip install 'retina[astro]'.")
        ) from exc


def save_raster(path: str, image: Image) -> None:
    """Save an :class:`Image` as TIFF (float) or PNG/JPEG/BMP (8-bit).

    Alpha (C = 2 or 4, see ``Image.nominal_channels``) is **honored in PNG and TIFF**; JPEG
    and BMP have none — it is flattened onto the nominal channels there, and JPEG2000 keeps
    its Pillow limit (RGB only). This is the natural outlet of ``CreateAlphaChannels``.
    """
    ext = os.path.splitext(path)[1].lower()
    data = image.data
    channels = data.shape[2]
    nominal = 1 if channels <= 2 else 3
    has_alpha = channels > nominal
    squeezed = data[:, :, 0] if channels == 1 else data
    if ext in _FLOAT_EXT:
        import tifffile

        photometric = "minisblack" if nominal == 1 else "rgb"
        # extrasamples: declares the supernumerary channel as NON-premultiplied alpha —
        # without which a strict reader would see a 4-sample TIFF with no meaning
        kwargs = {"extrasamples": ["unassoc"]} if has_alpha else {}
        tifffile.imwrite(path, np.ascontiguousarray(squeezed, dtype=np.float32),
                         photometric=photometric, **kwargs)
    elif ext in _BYTE_EXT:
        import imageio.v3 as iio

        byte = np.clip(squeezed, 0.0, 1.0)
        if has_alpha and ext not in {".png"}:
            # JPEG/BMP have no alpha: we flatten onto the nominal channels
            byte = byte[:, :, 0] if nominal == 1 else byte[:, :, :nominal]
        iio.imwrite(path, (byte * 255.0 + 0.5).astype(np.uint8))
    elif ext in _WEBP_EXT:
        from PIL import Image as PImage

        # WebP carries alpha, unlike JPEG: we keep it, it is the natural outlet of a cut-out
        # image. `lossless=True` because an already-processed astro image is not recompressed
        # lossily for a few kilobytes.
        octets_ = (np.clip(squeezed, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        if octets_.ndim == 2:
            pim = PImage.fromarray(octets_, "L")
        elif has_alpha and nominal == 1:  # gray + alpha: WebP only knows LA→RGBA
            pim = PImage.fromarray(
                np.dstack([octets_[:, :, 0]] * 3 + [octets_[:, :, 1]]), "RGBA")
        else:
            pim = PImage.fromarray(octets_, "RGBA" if has_alpha else "RGB")
        pim.save(path, format="WEBP", lossless=True)
    elif ext in _JP2_EXT | _JXL_EXT:
        if ext in _JXL_EXT:
            _load_jxl_plugin()
        from PIL import Image as PImage

        clipped = np.clip(squeezed, 0.0, 1.0)
        if has_alpha:  # Pillow/OpenJPEG limit: no alpha — flattened onto the nominals
            clipped = clipped[:, :, 0] if nominal == 1 else clipped[:, :, :nominal]
        if clipped.ndim == 2:  # gray → lossless 16-bit (better precision)
            pim = PImage.fromarray((clipped * 65535.0 + 0.5).astype(np.uint16))
        else:  # color → 8-bit RGB (limit of Pillow's JPEG2000 plugin)
            pim = PImage.fromarray((clipped[:, :, :3] * 255.0 + 0.5).astype(np.uint8), "RGB")
        if ext in _JXL_EXT:
            pim.save(path, format="JXL", lossless=True)
        else:
            pim.save(path, format="JPEG2000", irreversible=False)
    else:
        raise ValueError(_t("Unsupported raster extension: {ext}").format(ext=ext))
