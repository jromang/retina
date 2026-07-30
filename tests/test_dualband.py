"""``ExtractDualBand`` — Ha/OIII extraction from an OSC raw shot through a dual-band filter.

Fully headless (``execute_on_image`` on an ``Image``, no shell): this is the
"console-completeness" pillar — a process must be verifiable without an interface.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Image, get

#: Value laid on each kind of site in the pattern — a perfectly legible synthetic CFA:
#: red = 1, greens = 2, blue = 3. Ha must return 1 everywhere, OIII the mean of the greens, 2.
VALUES = {"R": 1.0, "G": 2.0, "B": 3.0}
PATTERNS = ("RGGB", "BGGR", "GRBG", "GBRG")


def _mosaic(pattern: str, h: int = 8, w: int = 6) -> np.ndarray:
    """CFA mosaic ``(h, w, 1)`` where each site carries the value of its colour."""
    plan = np.zeros((h, w), dtype=np.float32)
    for index, letter in enumerate(pattern):
        plan[index // 2 :: 2, index % 2 :: 2] = VALUES[letter]
    return plan[:, :, None]


def _extract(pattern: str, band: str, data: np.ndarray) -> np.ndarray:
    inst = get("ExtractDualBand")(pattern=pattern, band=band)
    return inst.execute_on_image(Image(data)).data


@pytest.mark.parametrize("pattern", PATTERNS)
def test_ha_takes_the_red_site(pattern):
    """Hα (656 nm) only comes through the red filter — whatever the order of the pattern."""
    ha = _extract(pattern, "ha", _mosaic(pattern))
    assert ha.shape == (4, 3, 1)
    assert np.allclose(ha, 1.0)


@pytest.mark.parametrize("pattern", PATTERNS)
def test_oiii_averages_the_two_greens(pattern):
    """OIII (500 nm) = mean of the two green sites: here (2+2)/2 = 2."""
    oiii = _extract(pattern, "oiii", _mosaic(pattern))
    assert oiii.shape == (4, 3, 1)
    assert np.allclose(oiii, 2.0)


def test_oiii_really_is_an_average_and_not_a_single_green():
    """Two greens with different gains: the output must land between them, not on one."""
    plan = np.zeros((4, 4), dtype=np.float32)
    plan[0::2, 0::2] = 1.0   # R
    plan[0::2, 1::2] = 2.0   # G1
    plan[1::2, 0::2] = 4.0   # G2
    plan[1::2, 1::2] = 3.0   # B
    oiii = _extract("RGGB", "oiii", plan[:, :, None])
    assert np.allclose(oiii, 3.0)  # (2 + 4) / 2


def test_the_geometry_is_indeed_halved():
    """Superpixel: one 2×2 block → one pixel. An odd row/column is truncated away."""
    ha = _extract("RGGB", "ha", _mosaic("RGGB", h=101, w=65))
    assert ha.shape == (50, 32, 1)
    assert ha.dtype == np.float32


def test_a_colour_image_is_refused_with_a_clear_message():
    """An already demosaiced RGB has no mosaic left: extracting would make no sense."""
    rgb = np.zeros((8, 8, 3), dtype=np.float32)
    with pytest.raises(ValueError) as exc:
        _extract("RGGB", "ha", rgb)
    message = str(exc.value)
    assert "ExtractDualBand" in message and "3" in message


def test_the_process_is_registered_and_not_maskable():
    cls = get("ExtractDualBand")
    assert cls.category == "Calibration"
    assert cls.is_maskable is False
    assert cls.realtime_capable() is False  # the geometry changes
    ids = [p.id for p in cls.parameters]
    assert ids == ["pattern", "band"]


def test_python_serialisation_replays_the_parameters():
    """Reproducibility (pillar 4): the instance is a replayable process icon."""
    inst = get("ExtractDualBand")(pattern="GBRG", band="oiii")
    source = inst.to_python_source()
    assert "GBRG" in source and "oiii" in source
