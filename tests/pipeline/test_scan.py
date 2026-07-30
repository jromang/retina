"""Frame scanning and classification."""

from __future__ import annotations

import os

import numpy as np
import pytest
from retina.pipeline.scan import (
    OUTPUT_DIR_NAME,
    FrameInfo,
    Inventory,
    classify,
    exclude,
    kind_from_name,
    pointing,
    reclassify,
    scan,
)


def test_the_scan_classifies_every_raw(raws_mono):
    inventory = scan(raws_mono)

    assert inventory.counts() == {"light": 8, "dark": 3, "flat": 6, "bias": 3}
    assert all(f.kind != "unknown" for f in inventory)
    assert inventory.root == os.path.abspath(raws_mono)


def test_keywords_take_precedence_and_are_traced(raws_mono):
    inventory = scan(raws_mono)
    lights = inventory.of_kind("light")

    assert {f.source for f in lights} == {"header"}
    assert {f.filter for f in lights} == {"L", "R"}
    assert {f.exposure for f in lights} == {5.0}
    assert {f.binning for f in lights} == {1}
    assert {f.temperature for f in lights} == {-10.0}
    assert {f.gain for f in lights} == {120.0}


def test_frames_without_imagetyp_fall_back_to_the_filename(raws_mono):
    """Two files in the dataset have no IMAGETYP — the fallback must catch them."""
    inventory = scan(raws_mono)
    by_name = [f for f in inventory if f.source == "filename"]

    assert {f.kind for f in by_name} == {"dark", "flat"}
    assert len(by_name) == 2
    # exposure and binning are still read from the header; only the type was missing
    assert all(f.exposure is not None for f in by_name)


def test_the_filename_heuristic_covers_the_aliases():
    assert kind_from_name("/data/M31/darks/img_001.fits") == "dark"
    assert kind_from_name("/data/offset_012.fits") == "bias"
    assert kind_from_name("/data/flat-dark_003.fit") == "dark"  # a flat-dark is still a dark
    assert kind_from_name("/data/bias_dark_001.fits") == "bias"  # bias wins over dark
    assert kind_from_name("/data/M31_Ha_0007.fits") is None


def test_a_freeform_imagetyp_is_normalized(tmp_path):
    from retina.io.fits import save_fits
    from retina.model.image import Image

    data = Image(np.zeros((8, 8, 1), dtype=np.float32))
    for value, expected in (("Dark Frame", "dark"), ("FLAT", "flat"),
                            ("Bias Frame", "bias"), ("light_frame", "light"),
                            ("Zero", "bias")):
        path = str(tmp_path / f"{expected}_{value.replace(' ', '')}.fits")
        save_fits(path, data, {"IMAGETYP": value})
        assert classify(path).kind == expected, value


def test_an_unknown_type_stays_unknown(tmp_path):
    """Never guess silently: `unknown` is worth more than a wrong master."""
    from retina.io.fits import save_fits
    from retina.model.image import Image

    path = str(tmp_path / "acquisition_0042.fits")
    save_fits(path, Image(np.zeros((8, 8, 1), dtype=np.float32)), {"OBJECT": "M31"})

    frame = classify(path)
    assert frame.kind == "unknown"
    assert frame.source == "default"


def test_an_unreadable_file_does_not_break_the_scan(tmp_path):
    (tmp_path / "dark_truncated.fits").write_bytes(b"not FITS at all")
    inventory = scan(str(tmp_path))

    assert len(inventory) == 1
    assert inventory.frames[0].kind == "dark"  # caught by the filename
    assert inventory.frames[0].source == "filename"


def test_the_scan_ignores_its_own_outputs(raws_mono, tmp_path):
    """A previous run must not be re-scanned as a folder of raws."""
    import shutil

    root = tmp_path / "session"
    shutil.copytree(raws_mono, root)
    outputs = root / OUTPUT_DIR_NAME / "masters"
    outputs.mkdir(parents=True)
    shutil.copy(next(root.glob("bias_*.fits")), outputs / "master_bias.fits")

    assert len(scan(str(root))) == 20


def test_the_scan_is_recursive_and_optionally_flat(raws_mono, tmp_path):
    import shutil

    root = tmp_path / "tree"
    (root / "darks").mkdir(parents=True)
    shutil.copy(os.path.join(raws_mono, "bias_001.fits"), root / "darks" / "d_001.fits")

    assert len(scan(str(root))) == 1
    assert len(scan(str(root), recursive=False)) == 0


def test_osc_is_detected_from_bayerpat(raws_osc):
    inventory = scan(raws_osc)

    assert inventory.is_osc
    assert inventory.counts() == {"light": 4, "dark": 3, "flat": 3, "bias": 3}
    assert all(f.filter is None for f in inventory.of_kind("light"))


def test_mono_is_not_osc(raws_mono):
    assert not scan(raws_mono).is_osc


def test_inventory_round_trip_json(raws_mono):
    inventory = scan(raws_mono)
    rebuilt = Inventory.from_dict(inventory.to_dict())

    assert rebuilt.root == inventory.root
    assert [f.path for f in rebuilt] == [f.path for f in inventory]
    assert rebuilt.counts() == inventory.counts()
    # raw keywords do not cross the transport: too bulky, and of no use to the UI
    assert rebuilt.frames[0].keywords == {}


def test_frame_info_exposes_its_name():
    frame = FrameInfo(path="/data/M31/light_001.fits")
    assert frame.name == "light_001.fits"


def test_scanning_a_missing_folder_raises():
    with pytest.raises(ValueError, match="not found"):
        scan("/path/that/does/not/exist")


# --- manual corrections --------------------------------------------------------------
#
# Classification infers; these operations are there to correct it. They must be named (rather
# than being plain attribute assignments) so that the wizard can echo them.

def inventory_of(*frames: FrameInfo) -> Inventory:
    return Inventory(root="/data", frames=list(frames))


def test_reclassifying_sets_the_type_and_marks_the_correction():
    frame = FrameInfo(path="/data/img_01.fits", kind="unknown")
    inventory = inventory_of(frame)

    reclassify(inventory, ["/data/img_01.fits"], "flat")

    assert frame.kind == "flat"
    # "user": this is no longer a guess, so the wizard stops flagging it as doubtful
    assert frame.source == "user"


def test_reclassifying_accepts_a_bare_path():
    frame = FrameInfo(path="/data/img_01.fits")
    reclassify(inventory_of(frame), "/data/img_01.fits", "dark")

    assert frame.kind == "dark"


def test_reclassifying_returns_the_inventory_so_the_echo_can_assign():
    """The echo reads ``inventory = retina.pipeline.reclassify(inventory, …)``."""
    inventory = inventory_of(FrameInfo(path="/data/img_01.fits"))

    assert reclassify(inventory, ["/data/img_01.fits"], "bias") is inventory


def test_reclassifying_to_an_unknown_type_raises():
    inventory = inventory_of(FrameInfo(path="/data/img_01.fits"))

    with pytest.raises(ValueError, match="Unknown type"):
        reclassify(inventory, ["/data/img_01.fits"], "banana")


def test_reclassifying_a_frame_that_is_not_there_raises():
    """A path matching nothing is a caller error, not a no-op."""
    inventory = inventory_of(FrameInfo(path="/data/img_01.fits"))

    with pytest.raises(ValueError, match="not in inventory"):
        reclassify(inventory, ["/data/other.fits"], "dark")


def test_excluding_then_bringing_back():
    frame = FrameInfo(path="/data/img_01.fits", kind="light")
    inventory = inventory_of(frame)

    exclude(inventory, ["/data/img_01.fits"])
    assert frame.excluded

    exclude(inventory, ["/data/img_01.fits"], excluded=False)
    assert not frame.excluded


def test_an_excluded_frame_stays_classified():
    """Excluding is not declassifying: the frame keeps its type, we simply do not want it."""
    frame = FrameInfo(path="/data/img_01.fits", kind="light", source="header")
    exclude(inventory_of(frame), ["/data/img_01.fits"])

    assert (frame.kind, frame.source) == ("light", "header")


def test_exclusion_survives_the_rpc_transport():
    frame = FrameInfo(path="/data/img_01.fits", kind="light")
    inventory = inventory_of(frame)
    reclassify(inventory, ["/data/img_01.fits"], "flat")
    exclude(inventory, ["/data/img_01.fits"])

    reread = Inventory.from_dict(inventory.to_dict())

    assert reread.frames[0].excluded
    assert reread.frames[0].source == "user"


def test_load_fits_header_does_not_read_the_pixels(raws_mono, monkeypatch):
    """The scan must stay usable on hundreds of 50 Mpx frames."""
    from astropy.io import fits
    from retina.io.fits import load_fits_header

    path = os.path.join(raws_mono, "bias_001.fits")
    headers = load_fits_header(path)
    assert headers["IMAGETYP"] == "Bias Frame"

    # guard: `fits.open` (which materializes the data on demand) is not the route taken
    def forbidden(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("load_fits_header must not open the whole file")

    monkeypatch.setattr(fits, "open", forbidden)
    assert load_fits_header(path)["EXPTIME"] == 0.0


# --- mount pointing -------------------------------------------------------------------
#
# This is what separates the panels of a mosaic (see test_groups.py). Three notations coexist
# in the wild, and all of them have to be read: nothing tells the user whether their capture
# software writes OBJCTRA rather than RA.

def test_pointing_is_read_in_decimal_degrees():
    assert pointing({"RA": 10.6847, "DEC": 41.2687}) == (10.6847, 41.2687)


def test_pointing_is_read_in_sexagesimal():
    """OBJCTRA is in **hours**, OBJCTDEC in degrees — the SharpCap/N.I.N.A. convention."""
    ra, dec = pointing({"OBJCTRA": "00 42 44.33", "OBJCTDEC": "+41 16 07.5"})

    assert ra == pytest.approx(10.6847, abs=1e-3)
    assert dec == pytest.approx(41.2687, abs=1e-3)


def test_sexagesimal_accepts_colons_and_a_sign():
    ra, dec = pointing({"OBJCTRA": "00:42:44.33", "OBJCTDEC": "-41:16:07.5"})

    assert ra == pytest.approx(10.6847, abs=1e-3)
    assert dec == pytest.approx(-41.2687, abs=1e-3)


def test_pointing_falls_back_to_the_crval_of_a_solved_frame():
    assert pointing({"CRVAL1": 202.4696, "CRVAL2": 47.1953}) == (202.4696, 47.1953)


def test_a_header_without_pointing_returns_nothing():
    assert pointing({"EXPTIME": 300.0}) == (None, None)


def test_an_out_of_range_pointing_is_rejected():
    """A wrong pointing is worth less than a missing one, which at least shows."""
    assert pointing({"RA": 10.0, "DEC": 191.0}) == (10.0, None)
    assert pointing({"RA": "n/a", "DEC": 41.0}) == (None, 41.0)


def test_the_scan_captures_the_pointing_of_the_lights(raws_mono):
    lights = scan(raws_mono).of_kind("light")

    assert all(f.ra is not None and f.dec is not None for f in lights)
    assert all(abs(f.dec - 41.2687) < 0.02 for f in lights)


def test_pointing_survives_the_rpc_transport(raws_mono):
    inventory = scan(raws_mono)
    reread = Inventory.from_dict(inventory.to_dict())

    assert [(f.ra, f.dec) for f in reread] == [(f.ra, f.dec) for f in inventory]


def test_an_inventory_saved_before_pointing_existed_still_loads():
    """Serialization stays tolerant: yesterday's inventory has no `ra` field."""
    previous = {"path": "/data/light_001.fits", "kind": "light", "exposure": 300.0}

    frame = FrameInfo.from_dict(previous)

    assert (frame.ra, frame.dec) == (None, None)
    assert frame.exposure == 300.0
