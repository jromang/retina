"""Persistent cache of frame measurements — across sessions, across projects.

The run cache (:mod:`.cache`) works per **step**: if the fingerprint of a measurement step
changes, the whole step is redone. That is the right granularity for a calibration, and the
wrong one for measurements — because the list of frames enters the fingerprint.

The consequence, and it is the problem this module solves: **adding a night to an existing
project re-measured the previous nights**. A hundred already measured subs paid again for
their star detection because twenty had been added. Here the unit is the **file**, so the
hundred old ones are served again and only the twenty new ones are measured.

The cache lives at the scale of the user, not of the project: the same raw frames
re-inventoried under another output folder, or reopened six months later, find their
measurements again. It is the same choice as PixInsight's ``FileDataCache`` — the machinery,
generalized so as to serve the registration stars too, lives in :mod:`.file_cache`; **the
on-disk format and the v2 key composition are unchanged**, no existing entry is invalidated
by the generalization (guaranteed by a frozen-key test).
"""

from __future__ import annotations

from .file_cache import DEFAULT_MAX_AGE_DAYS, FileDataCache, _default_root

__all__ = ["CACHE_VERSION", "DEFAULT_MAX_AGE_DAYS", "MeasureCache", "PhotometryCache",
           "_default_root", "clear_measure_cache", "clear_photometry_cache"]

#: format version. A change in the measurements produced must invalidate the whole cache:
#: otherwise we would serve again entries that are missing a column.
CACHE_VERSION = "2"


class MeasureCache(FileDataCache):
    """Already computed measurements, indexed by file **and** by detection settings."""

    filename = "measures.json"
    version = CACHE_VERSION


class PhotometryCache(FileDataCache):
    """Already measured photometry, indexed by file **and** by positions/aperture.

    Third domain of the mechanism, after frame measurements and registration stars. Its
    rationale is the same: a light curve is re-judged constantly (changing the differential
    mode, adding a comparison star to the computation, re-exporting) whereas the
    measurement itself does not change. Without this cache, each attempt would re-read a
    hundred subs.

    The star positions are part of the key, and that is accepted: **adding** a comparison
    re-measures the series. The unit cost is an aperture photometry at a few positions —
    nowhere near that of a full-frame star detection.
    """

    filename = "photometry.json"
    version = "1"


def clear_measure_cache() -> None:
    """Empties the persistent measurement cache.

    >>> retina.pipeline.clear_measure_cache()
    """
    MeasureCache().clear()


def clear_photometry_cache() -> None:
    """Empties the persistent photometry cache.

    >>> retina.pipeline.clear_photometry_cache()
    """
    PhotometryCache().clear()
