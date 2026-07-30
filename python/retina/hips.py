"""Sky references synthesized from an all-sky survey (HiPS, the ``hips2fits`` service).

Correcting a gradient calls for a reference without a gradient: an image of the same field
that is known to be flat. The problem is a *data* problem, not an algorithmic one, and the
CDS already publicly serves a FITS image reprojected onto whatever WCS it is given. No
database to build, no multi-gigabyte download, and a sky covered wherever DSS is — that is to
say, everywhere.

What this module **does not do**: photometry. A DSS plate is neither linear nor calibrated;
its value is the large-scale *shape* of the sky, which
:class:`~retina.processes.gradient.MultiscaleGradientCorrection` consumes through a robust
affine fit. Normalizing by percentiles is therefore amply sufficient, and the absolute scale
is beside the point.

**No ``retina/download.py`` here**, despite the signal placed in the header of ``samples.py``
("at the third caller, extract the loop"). That signal targets the *urllib* loop — block
reading, ``.part``, SHA-256 digest verified on the fly against a manifest. None of that
applies: astroquery does the HTTP and returns an in-memory ``HDUList``, and the content
depends on the requested WCS, so no digest is known in advance. Factoring here would produce
common code that nobody would run.
"""

from __future__ import annotations

import hashlib
import warnings
from datetime import UTC
from pathlib import Path

import numpy as np

from .i18n import N_
from .i18n import translate as _t
from .paths import cache_path

#: Surveys on offer, from the stable slug (process parameter, cache key, Python echo) to the
#: HiPS identifier of the CDS registry.
#:
#: **All FITS-tiled.** ``hips2fits`` only returns FITS for HiPS that store it; a color HiPS
#: such as ``CDS/P/DSS2/color`` is JPEG and returns only already-stretched 8-bit —
#: unusable for measuring a sky background, and the trap one falls into first because it is
#: the best-known survey.
SURVEYS: dict[str, str] = {
    # Total sky coverage: criterion number one against alternatives that do not cover it all.
    "dss2-red": "CDS/P/DSS2/red",
    "dss2-blue": "CDS/P/DSS2/blue",
    # Deeper and better sampled, but nothing south of δ ≈ −30°.
    "panstarrs-g": "CDS/P/PanSTARRS/DR1/g",
    "panstarrs-r": "CDS/P/PanSTARRS/DR1/r",
    "panstarrs-i": "CDS/P/PanSTARRS/DR1/i",
    # Large-scale Hα map: the only relevant reference for a gradient on a narrowband
    # exposure, where a DSS continuum says nothing about the signal.
    "halpha": "CDS/P/Finkbeiner",
    # Console-completeness escape hatch: any HiPS from the CDS registry.
    "custom": "",
}

#: Beyond this, the reference does not describe the field: the survey does not cover it
#: (PanSTARRS in the south), or the request half failed. Correcting a gradient over a third
#: of holes would invent structure where there is no data.
MAX_NAN_FRACTION = 0.3

#: Maximum side of the requested reference. All we consume of it is the large scale, so a
#: kilopixel suffices; the request is fast and the cache weighs a few hundred KB instead of
#: several tens of MB.
DEFAULT_MAX_SIZE = 1024


def hips_id_for(survey: str, hips_id: str = "") -> str:
    """HiPS identifier of a survey slug (``custom`` requires ``hips_id``)."""
    if survey == "custom" or survey not in SURVEYS:
        if not hips_id:
            raise ValueError(
                _t("Unknown survey {name!r} — give an explicit HiPS id.").format(name=survey)
            )
        return hips_id
    return hips_id or SURVEYS[survey]


def reduced_wcs(wcs, shape_hw: tuple[int, int], max_size: int = DEFAULT_MAX_SIZE):
    """Downsampled WCS covering the same celestial footprint, and its shape.

    ``query_with_wcs`` requires a ``pixel_shape`` to be set: it is what tells the service how
    many pixels to return, and without it the request goes out with no dimensions.
    """
    height, width = int(shape_hw[0]), int(shape_hw[1])
    factor = 1
    if max_size > 0:
        factor = max(1, int(np.ceil(max(height, width) / float(max_size))))
    small = wcs.deepcopy()
    if factor > 1:
        # `WCS.slice` applies exactly the convention of an N-pixel step (CRPIX and the scale
        # follow); redoing it by hand is the kind of computation where one is off by half a
        # pixel without ever noticing.
        small = wcs.slice((np.s_[::factor], np.s_[::factor]))
    shape = (int(np.ceil(height / factor)), int(np.ceil(width / factor)))
    small.pixel_shape = (shape[1], shape[0])  # (naxis1, naxis2) = (width, height)
    return small, shape


def cache_key(hips: str, wcs, shape: tuple[int, int]) -> str:
    """Short digest of (survey, requested grid) — the name of the cache file.

    The WCS is canonicalized by its FITS header, the same form projects use to serialize it:
    two distinct WCS objects describing the same grid return the same key, which is exactly
    what one wants from a cache.
    """
    try:
        header = wcs.to_header(relax=True).tostring(sep="\n", endcard=False, padding=False)
    except Exception:
        header = repr(wcs)
    seed = f"{hips}\n{header}\n{shape[0]}x{shape[1]}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def cache_file(survey: str, hips: str, wcs, shape: tuple[int, int]) -> Path:
    slug = survey if survey != "custom" else "custom"
    return cache_path("hips", f"{slug}-{cache_key(hips, wcs, shape)}.fits")


#: Service instances, tried in order. The mirror is not belt and braces: on 2026-07-29, the
#: main server accepted the connection then never answered, while ``alaskybis`` returned the
#: same field in twelve seconds. A service that hangs is worse than a service that is down —
#: without a fallback, the feature would simply have looked broken.
SERVERS = (
    "https://alasky.cds.unistra.fr/hips-image-services/hips2fits",
    "https://alaskybis.cds.unistra.fr/hips-image-services/hips2fits",
)

#: Astroquery's default is 30 s, which is short: returning a large field asks the service to
#: assemble dozens of tiles, and the first real attempt exceeded 30 s on an otherwise modest
#: request.
TIMEOUT = 120


def _query(hips: str, wcs) -> np.ndarray:
    """``hips2fits`` request — **the module's only network point**, hence the only one to
    intercept in a test."""
    from astroquery.hips2fits import hips2fits

    # `server` and `timeout` are **class attributes** frozen at import time from astroquery's
    # configuration: `conf.set_temp` does not reach them. We therefore set them on the
    # instance, and put them back as we found them.
    serveur_initial, delai_initial = hips2fits.server, hips2fits.timeout
    last: Exception | None = None
    try:
        for rank, server in enumerate(SERVERS):
            hips2fits.server, hips2fits.timeout = server, TIMEOUT
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    result = hips2fits.query_with_wcs(hips=hips, wcs=wcs, format="fits")
                data = result[0].data if isinstance(result, list) else result.data
                return np.asarray(data, dtype=np.float64)
            except Exception as exc:  # network, timeout, instance under maintenance
                last = exc
                if rank + 1 < len(SERVERS):
                    _advance(0.2, _t("Survey server unavailable, trying a mirror…"))
    finally:
        hips2fits.server, hips2fits.timeout = serveur_initial, delai_initial
    raise last if last is not None else RuntimeError("hips2fits")


def _normalize(plan: np.ndarray) -> np.ndarray:
    """Bring the plate into [0, 1] by robust percentiles.

    The absolute scale means nothing (a digitized photographic plate is not calibrated) and
    does not need to: the consumer's affine fit absorbs it. The percentiles, for their part,
    prevent a single saturated star from crushing everything else toward zero.
    """
    fini = np.isfinite(plan)
    if not fini.any():
        raise ValueError(_t("The survey returned no usable data for this field."))
    bottom, top = np.percentile(plan[fini], [0.5, 99.5])
    if not np.isfinite(top - bottom) or top <= bottom:
        bottom, top = float(np.min(plan[fini])), float(np.max(plan[fini]))
    if top <= bottom:
        return np.zeros_like(plan, dtype=np.float32)
    output = np.clip((plan - bottom) / (top - bottom), 0.0, 1.0)
    # Coverage holes take the median value: locally wrong, but neutral for a background fit,
    # whereas a zero would dig a crater there.
    return np.where(fini, output, np.median(output[fini])).astype(np.float32)


def _advance(fraction: float, message: str) -> None:
    monitor = None
    try:
        from .process import context

        monitor = context.get_monitor()
    except Exception:  # pragma: no cover — outside a process
        monitor = None
    if monitor is not None:
        monitor.report(fraction, message)


def fetch(wcs, shape_hw: tuple[int, int], survey: str = "dss2-red", *,
          hips_id: str = "", max_size: int = DEFAULT_MAX_SIZE,
          use_cache: bool = True) -> tuple[np.ndarray, object]:
    """Survey reference for the field described by ``wcs``/``shape_hw``.

    Returns ``(plane (h, w) float32 in [0, 1], WCS of that plane)``. The returned grid is
    downsampled (see ``max_size``): it covers the same celestial footprint as the image, at a
    resolution sufficient for a background correction.
    """
    hips = hips_id_for(survey, hips_id)
    small, shape = reduced_wcs(wcs, shape_hw, max_size)
    target = cache_file(survey, hips, small, shape)

    if use_cache and target.exists():
        from astropy.io import fits

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with fits.open(target) as hdul:
                return np.asarray(hdul[0].data, dtype=np.float32), small

    _advance(0.1, _t("Querying survey {name}…").format(name=hips))
    raw_data = _query(hips, small)
    if raw_data.ndim == 3:  # some HiPS return a one-plane cube
        raw_data = raw_data[0]
    fraction_nan = float(np.mean(~np.isfinite(raw_data))) if raw_data.size else 1.0
    if fraction_nan > MAX_NAN_FRACTION:
        # The percentage is formatted **before** entering the message: a literal `%` in a
        # msgid, followed by a letter, is read by Babel as a printf marker (`% o` = octal
        # conversion) and the translation refuses to compile.
        coverage = f"{100.0 * (1.0 - fraction_nan):.0f}%"
        raise ValueError(
            _t("Survey {name} covers only {coverage} of this field — "
               "choose a survey that covers it.").format(name=hips, coverage=coverage)
        )
    plan = _normalize(raw_data)
    _advance(0.9, _t("Survey reference ready"))

    if use_cache:
        _write_cache(target, plan, small, hips)
    return plan, small


def _write_cache(target: Path, plan: np.ndarray, wcs, hips: str) -> None:
    """Deposit the plane into the cache, going through a ``.part``.

    Not for network integrity — astroquery has already returned everything — but because a
    cancellation or a full disk would otherwise leave a truncated FITS that the read-back
    would take for a valid cache.
    """
    from datetime import datetime

    from astropy.io import fits

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        header = fits.Header()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            header.update(wcs.to_header(relax=True))
        # Provenance travels with the data: a cache file must be able to say where it comes
        # from and when, without which it is no more than an anonymous array on a disk.
        header["HIPSID"] = (hips, "HiPS survey identifier")
        header["HIPSDATE"] = (datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
                              "UTC of the hips2fits query")
        header["HIPSSVC"] = ("CDS hips2fits", "Service that rendered this reference")
        partial = target.with_suffix(".part")
        fits.PrimaryHDU(plan, header=header).writeto(partial, overwrite=True)
        partial.replace(target)
    except Exception:  # a failing cache must not make the request fail
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            partial = target.with_suffix(".part")
            if partial.exists():
                partial.unlink(missing_ok=True)


#: Survey labels, for the forms. Outside ``SURVEYS`` because the latter is a machine contract
#: (stable slugs), whereas this is displayed and translated.
SURVEY_LABELS = {
    "dss2-red": N_("DSS2 red (all-sky)"),
    "dss2-blue": N_("DSS2 blue (all-sky)"),
    "panstarrs-g": N_("Pan-STARRS DR1 g (dec > -30 deg)"),
    "panstarrs-r": N_("Pan-STARRS DR1 r (dec > -30 deg)"),
    "panstarrs-i": N_("Pan-STARRS DR1 i (dec > -30 deg)"),
    "halpha": N_("H-alpha full sky (Finkbeiner)"),
    "custom": N_("Custom HiPS id"),
}
