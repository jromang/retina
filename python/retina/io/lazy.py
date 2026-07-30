"""Reading images **in row bands**, without loading the whole frame.

This is what makes it possible to integrate a hundred 50 Mpx exposures: instead of stacking
60 GB, only one band of rows is materialized at a time. The difference is real for FITS,
where ``memmap`` lets the system read only the bytes asked for; for the other formats, which
no common library knows how to read partially, we fall back on a cached full load — the
contract is the same, the saving is not, and it is better said than letting one believe in a
universal lazy read.

The contract is deliberately tiny: ``shape``, ``band(y0, y1)``, ``close()``. It does not aim
to replace :func:`retina.io.load_image_array`, which remains the normal route.
"""

from __future__ import annotations

import os

import numpy as np

from ..i18n import translate as _t

FITS_EXT = (".fits", ".fit", ".fts")


def _full_scale(header, dtype) -> float:
    """Full scale of the type **after** BZERO/BSCALE are applied, or 1.0 if floating point.

    Reproduces astropy's convention, and therefore that of :func:`retina.io.fits.load_fits`:
    a BITPIX 16 paired with ``BZERO = 32768`` is *unsigned* 16-bit integer, whose full scale
    is 65535 and not 32767. Getting this wrong would shift the whole image by a factor of
    two — and only a band read out of tune with the full load would make it visible, which is
    the worst moment to find out.
    """
    bitpix = int(header.get("BITPIX", 0))
    if bitpix < 0 or not np.issubdtype(dtype, np.integer):
        return 1.0  # negative BITPIX = floating point, already normalized by convention
    bzero = float(header.get("BZERO", 0.0))
    bits = abs(bitpix)
    # BZERO = 2^(bits-1) is the FITS convention for "these signed integers are unsigned"
    non_signe = abs(bzero - 2 ** (bits - 1)) < 1.0
    return float(2**bits - 1) if non_signe else float(2 ** (bits - 1) - 1)


class LazyImage:
    """Band-wise reading. Usable as a context manager."""

    #: ``(height, width, channels)``
    shape: tuple[int, int, int]

    def band(self, y0: int, y1: int) -> np.ndarray:
        """Rows ``[y0, y1)`` as ``(h, W, C)`` float32."""
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> LazyImage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _ArrayImage(LazyImage):
    """Fallback: the array is already in memory, we merely slice it."""

    def __init__(self, data: np.ndarray) -> None:
        self._data = data
        self.shape = (data.shape[0], data.shape[1], data.shape[2])

    def band(self, y0: int, y1: int) -> np.ndarray:
        return np.ascontiguousarray(self._data[y0:y1], dtype=np.float32)

    def close(self) -> None:
        self._data = None  # type: ignore[assignment]


class _FitsImage(LazyImage):
    """FITS through ``memmap``: only the requested rows are actually read.

    The normalization reproduces exactly that of :func:`retina.io.fits.load_fits` — division
    by the full scale for integers, ``(C,H,W)`` → ``(H,W,C)`` reordering — otherwise a
    band-wise integration would not give the same result as a one-shot integration, and
    tiling would stop being an implementation detail.
    """

    def __init__(self, path: str) -> None:
        from astropy.io import fits

        # `do_not_scale_image_data` is what makes the memmap possible: astropy refuses to
        # map a file carrying BZERO/BSCALE, since applying the scale would require
        # materializing the array. Yet nearly every camera FITS carries them — a 16-bit CCD
        # stores its ADU as signed integers with BZERO = 32768. Without this, band reading
        # fell back on a full load exactly where it is useful.
        self._hdul = fits.open(path, memmap=True, do_not_scale_image_data=True)
        hdu = next((h for h in self._hdul if h.header.get("NAXIS", 0) > 0), self._hdul[0])
        self._data = hdu.data
        self._bzero = float(hdu.header.get("BZERO", 0.0))
        self._bscale = float(hdu.header.get("BSCALE", 1.0))
        self._scale = _full_scale(hdu.header, self._data.dtype)

        if self._data.ndim == 2:
            self._transpose = False
            height, width, channels = self._data.shape[0], self._data.shape[1], 1
        elif self._data.ndim == 3 and self._data.shape[0] <= 4:
            self._transpose = True
            channels, height, width = self._data.shape
        else:
            raise ValueError(
                _t("Unsupported FITS dimensionality: {shape}").format(shape=self._data.shape)
            )
        self.shape = (int(height), int(width), int(channels))

    def band(self, y0: int, y1: int) -> np.ndarray:
        raw_data = self._data[:, y0:y1, :] if self._transpose else self._data[y0:y1]
        data = np.asarray(raw_data, dtype=np.float32)
        if self._bscale != 1.0:
            data = data * self._bscale
        if self._bzero != 0.0:
            data = data + self._bzero
        if self._scale != 1.0:
            data = data / self._scale
        if self._transpose:
            data = np.transpose(data, (1, 2, 0))
        elif data.ndim == 2:
            data = data[:, :, np.newaxis]
        return np.ascontiguousarray(data)

    def close(self) -> None:
        if self._hdul is not None:
            self._hdul.close()
            self._hdul = None  # type: ignore[assignment]
            self._data = None  # type: ignore[assignment]


def open_lazy(path: str) -> LazyImage:
    """Open an image for band-wise reading.

    >>> with open_lazy("light_001.fits") as image:
    ...     first_row = image.band(0, 1)
    """
    if os.path.splitext(path)[1].lower() in FITS_EXT:
        try:
            return _FitsImage(path)
        except Exception:
            # Exotic FITS (compressed, unusual multi-extension): rather than failing, we
            # fall back on the full load, which knows how to read it.
            pass
    from . import load_image_array

    return _ArrayImage(load_image_array(path).astype(np.float32))
