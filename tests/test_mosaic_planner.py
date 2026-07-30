"""Mosaic planner — the inverse of `detect_panels`: preparing rather than recovering.

No network: `set_center` replaces name resolution through Sesame, just as `set_objects` does
for `FindingChart`.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image
from retina.io.fits import save_fits
from retina.processes.mosaic import MosaicPlanner


def _separation(a: dict, b: dict) -> float:
    """Angular separation in degrees, by haversine — as in `groups.angular_separation`."""
    ra1, dec1, ra2, dec2 = (np.radians(v) for v in (a["ra"], a["dec"], b["ra"], b["dec"]))
    d = (np.sin((dec2 - dec1) / 2) ** 2
         + np.cos(dec1) * np.cos(dec2) * np.sin((ra2 - ra1) / 2) ** 2)
    return float(np.degrees(2 * np.arcsin(np.sqrt(d))))


def _planner(**kwargs) -> MosaicPlanner:
    proc = MosaicPlanner(fov_width=1.0, fov_height=0.8, **kwargs)
    return proc.set_center(210.0, 33.0)


def test_a_3x2_grid_yields_six_pointings():
    panels = _planner(tiles_x=3, tiles_y=2).plan()

    assert len(panels) == 6
    assert [p["panel"] for p in panels] == ["P01", "P02", "P03", "P04", "P05", "P06"]


def test_the_step_respects_the_overlap():
    """20 % overlap → neighbouring centres sit at 80 % of the field from one another."""
    panels = _planner(tiles_x=3, tiles_y=1, overlap=20.0).plan()

    deviation = _separation(panels[0], panels[1])
    assert deviation == pytest.approx(0.8, rel=0.03)  # 0.8 × the 1° field width


def test_without_overlap_the_step_equals_the_field():
    panels = _planner(tiles_x=2, tiles_y=1, overlap=0.0).plan()
    assert _separation(panels[0], panels[1]) == pytest.approx(1.0, rel=0.03)


def test_the_mosaic_is_centred_on_the_target():
    """The barycentre of the pointings must land back on the target, not beside it."""
    panels = _planner(tiles_x=4, tiles_y=3).plan()

    center = {"ra": float(np.mean([p["ra"] for p in panels])),
              "dec": float(np.mean([p["dec"] for p in panels]))}
    assert _separation(center, {"ra": 210.0, "dec": 33.0}) < 0.02


def test_the_step_does_not_tighten_at_high_declination():
    """The trap the tangent plane avoids: a constant step in RA shrinks as cos δ.

    At +80° of declination, cos δ ≈ 0.17: naive arithmetic on the RA values would give tiles
    six times too close together, and the mosaic would cover only a sixth of the field.
    """
    proc = MosaicPlanner(fov_width=1.0, fov_height=1.0, tiles_x=2, tiles_y=1, overlap=0.0)
    panels = proc.set_center(210.0, 80.0).plan()

    assert _separation(panels[0], panels[1]) == pytest.approx(1.0, rel=0.05)


def test_the_field_is_deduced_from_a_reference_header(tmp_path):
    """A 4000 px sensor at 3.76 µm on a 530 mm focal length.

    Scale: 206.265 × 3.76 / 530 = 1.463″/px, so 4000 × 1.463 = 5853″ = **1.626°**.
    """
    path = tmp_path / "reference.fits"
    save_fits(str(path), Image(np.zeros((3000, 4000, 1), np.float32)),
              {"XPIXSZ": 3.76, "FOCALLEN": 530.0})

    width, height = MosaicPlanner(reference_frame=str(path)).field()

    assert width == pytest.approx(1.626, rel=0.02)
    assert height == pytest.approx(1.219, rel=0.02)
    assert width / height == pytest.approx(4000 / 3000, rel=1e-6)


def test_a_header_without_optics_says_so(tmp_path):
    path = tmp_path / "silent.fits"
    save_fits(str(path), Image(np.zeros((10, 10, 1), np.float32)), {})

    with pytest.raises(ValueError, match="lacks XPIXSZ"):
        MosaicPlanner(reference_frame=str(path)).field()


def test_without_a_field_or_a_reference_the_process_refuses():
    with pytest.raises(ValueError, match="fov_width"):
        MosaicPlanner().set_center(1.0, 2.0).field()


def test_without_a_target_the_process_refuses():
    with pytest.raises(ValueError, match="no target"):
        MosaicPlanner(fov_width=1.0, fov_height=1.0).center()


def test_a_target_given_as_coordinates_is_read_directly():
    assert MosaicPlanner(target="210.5,-33.25").center() == (210.5, -33.25)


def test_execute_global_creates_a_solved_map_and_a_csv(tmp_path):
    app = Application()
    output = tmp_path / "pointings.csv"
    proc = _planner(tiles_x=2, tiles_y=2, size=200, output_path=str(output))

    assert proc.execute_global(app)

    map_ = app.windows[-1]
    assert map_.id == "MosaicPlan"
    assert map_.has_astrometric_solution  # superimposable on the rest, celestial readout at once
    assert proc.result["n_panels"] == 4
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "name,ra_deg,dec_deg"
    assert len(lines) == 5
    # The map really carries something drawn, not a flat background.
    assert float(map_.main_view.image.data.std()) > 0.0
