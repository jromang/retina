"""The WCS of an already-solved file survives opening, saving and reloading.

Before this change, only a ``PlateSolve`` (or reading back a ``.retina``) would set
``ImageWindow.wcs``: opening an integrated frame produced by the pipeline, by Siril or by
another suite gave a window with no astrometry, even though the solution was sitting in its
header.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image
from retina.io.fits import celestial_wcs, save_fits, wcs_keywords


def _synthetic_wcs(h: int, w: int):
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [w / 2, h / 2]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [10.0, 20.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def _write_solved(path, h=32, w=48):
    """Test FITS carrying a WCS in its header."""
    image = Image(np.full((h, w, 1), 0.25, dtype=np.float32))
    save_fits(str(path), image, wcs_keywords(_synthetic_wcs(h, w)))
    return image


# --- celestial_wcs ---------------------------------------------------------------------

def test_reads_the_wcs_from_the_keywords():
    keywords = wcs_keywords(_synthetic_wcs(32, 48))
    read_back = celestial_wcs(keywords)
    assert read_back is not None
    sky = read_back.pixel_to_world(23.0, 15.0)
    assert sky.ra.deg == pytest.approx(10.0, abs=1e-6)
    assert sky.dec.deg == pytest.approx(20.0, abs=1e-6)


def test_without_a_wcs_returns_none():
    assert celestial_wcs({"EXPTIME": 120.0, "FILTER": "Ha"}) is None
    assert celestial_wcs({}) is None


def test_a_broken_header_never_raises():
    """A partial or nonsensical WCS must not stop the image from opening."""
    # projection named but no scale: the solution describes nothing usable
    assert celestial_wcs({"CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
                          "CDELT1": 0.0, "CDELT2": 0.0}) is None
    # impossible value types: we expect no exception, we expect None
    assert celestial_wcs({"CTYPE1": object(), "CRVAL1": "blue"}) is None


def test_wcs_keywords_without_a_solution_returns_an_empty_dict():
    assert wcs_keywords(None) == {}


# --- app.open / save / reload ------------------------------------------------------------

def test_opening_a_solved_file_sets_the_solution(tmp_path):
    file = tmp_path / "integrated.fits"
    _write_solved(file)

    app = Application()
    win = app.open(str(file))

    assert win.has_astrometric_solution
    sky = win.image_to_celestial(23.0, 15.0)
    assert sky.ra.deg == pytest.approx(10.0, abs=1e-6)


def test_opening_a_file_without_a_wcs_leaves_the_window_unsolved(tmp_path):
    file = tmp_path / "raw.fits"
    save_fits(str(file), Image(np.zeros((16, 16, 1), np.float32)), {"EXPTIME": 60.0})

    win = Application().open(str(file))

    assert not win.has_astrometric_solution


def test_the_live_solution_is_written_and_wins_over_inherited_keywords(tmp_path):
    """A PlateSolve done inside Retina used to be lost on save."""
    source = tmp_path / "source.fits"
    _write_solved(source)
    app = Application()
    win = app.open(str(source))
    # as after a plate-solve: the live solution points somewhere other than the header read
    other = _synthetic_wcs(32, 48)
    other.wcs.crval = [200.0, -30.0]
    win.wcs = other

    output = tmp_path / "solved.fits"
    app.save(str(output))

    reread = Application().open(str(output))
    sky = reread.image_to_celestial(23.0, 15.0)
    assert sky.ra.deg == pytest.approx(200.0, abs=1e-6)
    assert sky.dec.deg == pytest.approx(-30.0, abs=1e-6)


def test_reloading_reads_the_solution_of_the_new_content(tmp_path):
    """`replace_image` drops the old solution; the reloaded file's own replaces it."""
    file = tmp_path / "light.fits"
    save_fits(str(file), Image(np.zeros((32, 48, 1), np.float32)), {})
    app = Application()
    win = app.open(str(file))
    assert not win.has_astrometric_solution

    _write_solved(file)  # the file was solved externally in the meantime
    app.reload()

    assert win.has_astrometric_solution
