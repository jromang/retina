"""Reuse of supplied masters, and plate solving of the final images.

The last two gaps that weighed on everyday use: rebuilding an hour's worth of masters one
already owns, and delivering images with no astrometry.
"""

from __future__ import annotations

import os
import shutil

import numpy as np
import pytest
from retina.io.fits import load_fits_header, save_fits
from retina.model.image import Image
from retina.pipeline import plan, scan
from retina.pipeline.presets import Preset
from retina.pipeline.runner import run
from retina.pipeline.scan import classify
from retina.process.registry import get

# --- detecting a master ------------------------------------------------------------------

@pytest.mark.parametrize("path, kind", [
    ("/data/masters/masterDark_300s.fits", "dark"),
    ("/data/masterBias.fits", "bias"),
    ("/data/master_flat_L.fit", "flat"),
    ("/data/MASTERS/bias_stack.fits", "bias"),
])
def test_a_master_is_recognized_by_its_path(path, kind):
    frame = classify(path, keywords={})

    assert frame.is_master is True
    assert frame.kind == kind


def test_the_master_prefix_does_not_hide_the_type():
    """``masterDark`` glues the word to the prefix: the patterns require a boundary."""
    assert classify("/data/masterDark_300s.fits", keywords={}).kind == "dark"


def test_the_pattern_does_not_spill_onto_neighboring_words():
    assert classify("/data/nodark_01.fits", keywords={}).kind == "unknown"


def test_a_light_is_never_taken_for_a_master():
    """An object named ``Master`` would make its subs pass for masters."""
    frame = classify("/data/M31_Master/light_001.fits", keywords={})

    assert frame.kind == "light"
    assert frame.is_master is False


def test_the_group_exposes_its_master(tmp_path):
    from retina.pipeline.groups import group_frames

    path = str(tmp_path / "masterDark_5s.fits")
    save_fits(path, Image(np.zeros((8, 8, 1), dtype=np.float32)),
              {"EXPTIME": 5.0, "XBINNING": 1})
    groups = group_frames([classify(path)])

    assert groups[0].master == path


# --- reuse --------------------------------------------------------------------------------

@pytest.fixture
def library(raws_mono, tmp_path):
    """A folder of lights alone, plus a library of already-built masters."""
    first = plan(scan(raws_mono), "auto", output_dir=str(tmp_path / "run1"))
    report = run(first)

    session = tmp_path / "session"
    (session / "masters").mkdir(parents=True)
    for name in os.listdir(raws_mono):
        if name.startswith("light"):
            shutil.copy(os.path.join(raws_mono, name), session / name)
    for key, path in report.outputs.items():
        if key.startswith("master_"):
            shutil.copy(path, session / "masters" / os.path.basename(path))
    return str(session)


def test_supplied_masters_replace_building_them(library, tmp_path):
    p = plan(scan(library), "auto", output_dir=str(tmp_path / "run2"))

    assert not [s for s in p.steps if s.id.startswith("master_")]
    assert sum("reusing supplied master" in n for n in p.notes) == 4  # bias, dark, flat L, flat R


def test_supplied_masters_are_really_wired_in(library, tmp_path):
    p = plan(scan(library), "auto", output_dir=str(tmp_path / "run2"))
    calibration = p.step("calibrate_light_L_5s_bin1_g120_m10C").processes[0]

    assert "masters" in calibration.master_dark
    assert os.path.exists(calibration.master_dark)


def test_the_pipeline_completes_with_supplied_masters(library, tmp_path):
    p = plan(scan(library), "auto", output_dir=str(tmp_path / "run2"))
    report = run(p)

    assert len(report.results) == 2
    assert all(os.path.exists(r) for r in report.results)


def test_a_supplied_master_flat_is_not_recalibrated(library, tmp_path):
    """It already has been: recalibrating it would subtract the bias a second time."""
    p = plan(scan(library), "auto", output_dir=str(tmp_path / "run2"))

    assert not [s for s in p.steps if s.id.startswith("calibrate_flat")]


# --- the masters we write describe themselves ---------------------------------------------

def test_a_master_carries_its_identity(raws_mono, tmp_path):
    """Without this, a later run that finds it again would not know what it applies to."""
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path))
    report = run(p)
    header = load_fits_header(report.outputs["master_dark_5s_bin1_g120_m10C"])

    assert header["IMAGETYP"] == "Master Dark"
    assert header["EXPTIME"] == 5.0
    assert header["GAIN"] == 120.0
    assert header["SET-TEMP"] == -10.0
    assert header["XBINNING"] == 1
    assert header["INSTRUME"] == "Retina Synthetic"


def test_a_master_flat_carries_its_filter(raws_mono, tmp_path):
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path))
    report = run(p)

    assert load_fits_header(report.outputs["master_flat_L_bin1_g120_m10C"])["FILTER"] == "L"


def test_a_master_read_back_finds_the_same_key(library):
    """The loop closes: what we write groups the same way as what produced it."""
    groups = {g.key for g in scan(library).groups() if g.kind != "light"}

    assert groups == {"bias_bin1_g120_m10C", "dark_5s_bin1_g120_m10C",
                       "flat_L_bin1_g120_m10C", "flat_R_bin1_g120_m10C"}


# --- astrometry -----------------------------------------------------------------------------

def test_platesolve_is_disabled_by_default(raws_mono, tmp_path):
    """The offline solver downloads its indexes on first call: not on our initiative."""
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path))

    assert not [s for s in p.steps if s.id.startswith("platesolve_")]


def test_platesolve_is_added_after_the_crop(raws_mono, tmp_path):
    """Cropping moves the origin: a WCS computed before it would be wrong."""
    p = plan(scan(raws_mono), Preset(name="ps", platesolve=True), output_dir=str(tmp_path))
    names = [s.id for s in p.steps]

    assert names.index("autocrop_light_L_5s_bin1_g120_m10C") < \
        names.index("platesolve_light_L_5s_bin1_g120_m10C")
    assert p.step("platesolve_light_L_5s_bin1_g120_m10C").inputs == \
        p.step("autocrop_light_L_5s_bin1_g120_m10C").outputs


def test_the_advertised_result_is_the_solved_image(raws_mono, tmp_path):
    p = plan(scan(raws_mono), Preset(name="ps", platesolve=True), output_dir=str(tmp_path))

    assert all(r.endswith("_wcs.fits") for r in p.results)


def test_an_unsolved_astrometry_does_not_stop_the_batch(raws_mono, tmp_path):
    """An image without a WCS is not wrong — it is the opposite of a failed calibration."""
    p = plan(scan(raws_mono), Preset(name="ps", platesolve=True),
             output_dir=str(tmp_path))
    report = run(p)

    assert len(report.results) == 2
    assert all(os.path.exists(r) for r in report.results)
    assert any("astrometry" in n for n in report.notes)


def test_the_wcs_is_written_into_the_header(tmp_path, monkeypatch):
    """When solving succeeds, the solution must follow the image."""
    from astropy.wcs import WCS

    fake = WCS(naxis=2)
    fake.wcs.crpix = [64.0, 64.0]
    fake.wcs.crval = [10.68, 41.27]
    fake.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    monkeypatch.setattr(get("PlateSolve"), "solve", lambda self, target: fake)

    p = plan(scan_lights(tmp_path), Preset(name="ps", platesolve=True, register=False,
                                           measure=False, autocrop=False),
             output_dir=str(tmp_path / "out"))
    report = run(p)
    header = load_fits_header(report.results[0])

    assert header["CTYPE1"] == "RA---TAN"
    assert header["CRVAL1"] == pytest.approx(10.68)


def scan_lights(tmp_path):
    from retina.pipeline.synthetic import make_dataset

    source = tmp_path / "raws"
    source.mkdir()
    make_dataset(str(source), "mono", filters=("L",))
    return scan(str(source))


def test_platesolve_solves_an_image_without_a_window():
    """The pipeline works file to file: it has no window at hand."""
    process = get("PlateSolve")()
    image = Image(np.zeros((8, 8, 1), dtype=np.float32))

    assert process._pixels(image).shape == (8, 8, 1)
