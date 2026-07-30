"""FITS I/O through astropy → Image (and back).

Normalizes to ``(H, W, C)`` float32. A 2D FITS → 1 channel; a 3D FITS in ``(C, H, W)``
order (small first axis) → ``(H, W, C)``.
"""

from __future__ import annotations

import contextlib

import numpy as np

from ..i18n import translate as _t
from ..model.image import Image


def load_fits(path: str) -> tuple[Image, dict]:
    """Load a FITS. Returns (Image, header keywords)."""
    from astropy.io import fits

    with fits.open(path) as hdul:
        hdu = next((h for h in hdul if getattr(h, "data", None) is not None), hdul[0])
        raw = hdu.data
        data = np.asarray(raw, dtype=np.float32)
        # Integer FITS store raw ADU (e.g. 0..65535 in 16 bits): we normalize to [0,1] —
        # the linear convention the STF and the display expect (identity clim). Floating
        # point FITS (BITPIX < 0) are assumed already normalized.
        if np.issubdtype(np.asarray(raw).dtype, np.integer):
            data /= float(np.iinfo(np.asarray(raw).dtype).max)
        keywords = {k: hdu.header[k] for k in hdu.header if k}

    if data.ndim == 2:
        data = data[:, :, np.newaxis]
    elif data.ndim == 3:
        # Color FITS = (C, H, W); we reorder to (H, W, C)
        if data.shape[0] <= 4:
            data = np.transpose(data, (1, 2, 0))
    else:
        raise ValueError(
            _t("Unsupported FITS dimensionality: {shape}").format(shape=data.shape)
        )

    return Image(np.ascontiguousarray(data)), keywords


def load_fits_header(path: str) -> dict:
    """Header keywords **without reading the pixels**.

    Scanning a folder of raw frames (``retina.pipeline``) only cares about ``IMAGETYP``,
    ``FILTER``, ``EXPTIME``…: loading the data of hundreds of 50 Mpx frames just to throw it
    away would make the inventory unusable. ``getheader`` reads only the header block.
    """
    from astropy.io import fits

    header = fits.getheader(path)
    if header.get("NAXIS", 0) == 0:
        # Primary HDU with no data (MEF convention): the useful keywords are in the first
        # extension carrying the image.
        with fits.open(path) as hdul:
            hdu = next((h for h in hdul if h.header.get("NAXIS", 0) > 0), hdul[0])
            merged = {k: header[k] for k in header if k}
            merged.update({k: hdu.header[k] for k in hdu.header if k})
            return merged
    return {k: header[k] for k in header if k}


def celestial_wcs(keywords: dict):
    """Astrometric solution carried by FITS keywords, or ``None``.

    An already-solved file — an integration out of the pipeline, out of Siril or out of
    another suite — carries its WCS in its header. Without this read, opening it in Retina
    gave a window with no astrometry: no celestial readout, no annotation, no survey
    reference, until a ``PlateSolve`` had been rerun on a field whose solution was already
    there, in plain sight.

    **Never raises.** A header with a shaky WCS (partial keywords, unknown projection, null
    scale) must not prevent the image from opening: we return ``None``, and the window
    behaves as before. Astropy's ``FITSFixedWarning`` — which *repair* old conventions — are
    silenced: they are expected on period files and announce nothing actionable to the user.
    """
    import warnings

    try:
        from astropy.io import fits
        from astropy.wcs import WCS

        header = fits.Header()
        for key, value in keywords.items():
            with contextlib.suppress(Exception):
                header[key] = value
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wcs = WCS(header, relax=True)
        if not wcs.has_celestial:
            return None
        # A WCS with more than two axes (spectral cube, color plane) is reduced to its
        # celestial part; a WCS already 2D is returned **as is**, because `.celestial`
        # rebuilds a sub-WCS and would lose the SIP distortion of a plate-solve on the
        # way — precisely what makes the solution accurate.
        celestial = wcs if wcs.naxis == 2 else wcs.celestial
        from astropy.wcs.utils import proj_plane_pixel_scales

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            scales = proj_plane_pixel_scales(celestial)
        if not all(np.isfinite(s) and s > 0.0 for s in scales):
            return None
        return celestial
    except Exception:
        return None


def observation_jd(keywords: dict) -> float | None:
    """Julian date (UTC) of the **middle of the exposure**, or ``None`` if the header is mute.

    The middle and not the start: a light curve dates an *integrated* flux, and taking the
    start shifts every point by half an exposure — one hour over a two-hour series at 300 s
    per exposure, which is visible on an exoplanet transit.

    We return **JD**, not BJD: the barycentric correction requires the observer's position
    and the target's, and the AAVSO format accepts JD (``#DATE=JD``). Siril makes the same
    choice.

    Precision: a modern JD is worth ~2.46 million, and a float64 has a step of ~50 µs there.
    That is the floor of what we return, far below what a light curve calls for. Half the
    exposure time is added **before** the conversion, inside astropy's arithmetic, so as not
    to add a second rounding error to the first.
    """
    start = keywords.get("DATE-OBS") or keywords.get("DATE_OBS")
    if not start:
        return None
    try:
        import astropy.units as u
        from astropy.time import Time

        instant = Time(str(start).strip(), format="isot", scale="utc")
        frame = float(keywords.get("EXPTIME", keywords.get("EXPOSURE", 0.0)) or 0.0)
        return float((instant + (frame / 2.0) * u.s).jd)
    except Exception:
        return None


def observation_airmass(keywords: dict, jd: float | None = None,
                        ra: float | None = None, dec: float | None = None) -> float | None:
    """Airmass: the header's, otherwise computed if the site is known, otherwise ``None``.

    The order matters. The ``AIRMASS`` keyword is written by acquisition software (NINA, SGP)
    that knows the mount; recomputing it over the top would amount to preferring our estimate
    to theirs. The computation therefore only steps in for want of better, and does not
    invent a site: without ``SITELAT``/``SITELONG``, we return ``None`` — which the AAVSO
    export renders as ``na``, which is honest, where a made-up value would not be.
    """
    for key in ("AIRMASS", "SECZ"):
        value = keywords.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    lat = keywords.get("SITELAT", keywords.get("LAT-OBS", keywords.get("OBSGEO-B")))
    lon = keywords.get("SITELONG", keywords.get("LONG-OBS", keywords.get("OBSGEO-L")))
    if lat is None or lon is None or jd is None or ra is None or dec is None:
        return None
    try:
        import astropy.units as u
        from astropy.coordinates import AltAz, EarthLocation, SkyCoord
        from astropy.time import Time

        lieu = EarthLocation(lat=float(lat) * u.deg, lon=float(lon) * u.deg,
                             height=float(keywords.get("SITEELEV", 0.0) or 0.0) * u.m)
        target = SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg)
        altaz = target.transform_to(AltAz(obstime=Time(jd, format="jd"), location=lieu))
        if altaz.alt.deg <= 0.0:  # below the horizon: the secant no longer means anything
            return None
        return float(altaz.secz)
    except Exception:
        return None


def wcs_keywords(wcs) -> dict:
    """FITS keywords describing ``wcs`` (``{}`` if absent or unreadable).

    Symmetric with :func:`celestial_wcs`: without it, a ``PlateSolve`` done inside Retina
    would be lost on saving, and reopening the file would call for solving it again.
    ``relax=True`` keeps the extended conventions (SIP), as in projects.
    """
    if wcs is None:
        return {}
    try:
        return dict(wcs.to_header(relax=True))
    except Exception:
        return {}


#: Keywords **never** copied from a source image into a file we write.
#:
#: ``BZERO``/``BSCALE``/``BLANK`` describe the integer scaling of the source file (a 16-bit
#: CCD stores its ADU as signed integers with ``BZERO = 32768``). Copying them into a file
#: we write in **normalized** float32 is a silent catastrophe: astropy reapplies them on
#: read-back and adds 32768 to every pixel. The rest describes the file structure, which
#: astropy sets itself.
STRUCTURAL_KEYWORDS = frozenset({
    "SIMPLE", "EXTEND", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "NAXIS3",
    "BZERO", "BSCALE", "BLANK", "DATAMIN", "DATAMAX",
})


def save_fits(path: str, image: Image, keywords: dict | None = None) -> None:
    from astropy.io import fits

    data = image.data
    # FITS expects (C, H, W) — or plain (H, W) in monochrome; our model is (H, W, C)
    out = data[:, :, 0] if data.shape[2] == 1 else np.transpose(data, (2, 0, 1))
    hdu = fits.PrimaryHDU(np.ascontiguousarray(out, dtype=np.float32))
    if keywords:
        for k, v in keywords.items():
            if str(k).upper() in STRUCTURAL_KEYWORDS:
                continue
            # other structural keywords are set by astropy itself and refuse to be
            # rewritten: we do not insist
            with contextlib.suppress(Exception):
                hdu.header[k] = v
    hdu.writeto(path, overwrite=True)
