"""Linear patterns (CMOS banding) and the pipeline's LPS step.

The test field carries two things that must be told apart: an injected **column pattern**,
which has to go, and a **genuine background gradient**, which must on no account be touched.
A corrector that cannot separate them erases one or leaves the other.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from retina.model.image import Image
from retina.model.window import ImageWindow
from retina.process.registry import get
from retina.processes.linearpattern import DEFECTS_TAG, detect_linear_defects

COLUMNS = [30, 31, 90, 150, 151, 152, 220]
AMPLITUDES = [0.02, -0.015, 0.03, -0.02, 0.02, -0.03, 0.025]


def striped_field(size=256, noise=0.003, gradient=0.04, seed=8):
    """Background gradient + column pattern + noise."""
    rng = np.random.default_rng(seed)
    _, xx = np.mgrid[0:size, 0:size]
    background = 0.10 + gradient * (xx / size)
    pattern = np.zeros(size)
    kept_rows = [c for c in COLUMNS if c < size]
    pattern[kept_rows] = AMPLITUDES[:len(kept_rows)]
    image = background + rng.normal(0, noise, (size, size)) + pattern[None, :]
    return Image(image[:, :, None].astype(np.float32)), background


# --- detection ------------------------------------------------------------------------

def test_every_injected_column_is_found():
    image, _ = striped_field()

    defects = detect_linear_defects(image.data, threshold_sigma=5.0)

    found_items = {d["index"] for d in defects}
    assert set(COLUMNS) <= found_items
    # A few false positives are acceptable: they cost the correction nothing, since it then
    # shifts a column by less than the noise.
    assert len(found_items - set(COLUMNS)) <= 8


def test_a_field_without_a_pattern_returns_almost_nothing():
    rng = np.random.default_rng(1)
    own = np.full((256, 256, 1), 0.1) + rng.normal(0, 0.003, (256, 256, 1))

    defects = detect_linear_defects(own.astype(np.float32), threshold_sigma=5.0)

    assert len(defects) <= 8


def test_the_json_export_can_be_read_back(tmp_path):
    image, _ = striped_field()
    target = tmp_path / "defects.json"

    process = get("LinearDefectDetection")(output_path=str(target))
    process.execute_on_image(image)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["version"] == 1
    assert {d["index"] for d in loaded["defects"]} >= set(COLUMNS)


def test_the_defects_are_drawn():
    image, _ = striped_field()
    window = ImageWindow(image)

    get("LinearDefectDetection")().execute_on(window.main_view)

    frames = [o for o in window.viewport.overlays if o.get("tag") == DEFECTS_TAG]
    assert frames and frames[0]["kind"] == "lines"


# --- correction -----------------------------------------------------------------------

def test_the_pattern_is_removed_and_the_gradient_survives():
    """Both halves of the promise, in a single test — they do not come apart."""
    image, background = striped_field()

    output = get("LinearPatternSubtraction")().execute_on_image(image).data[:, :, 0]

    residual = np.median(output, axis=0) - np.median(background, axis=0)
    assert np.abs(residual[COLUMNS]).max() < 0.002        # pattern of 0.03 → below 0.002
    slope_before = np.polyfit(np.arange(256), np.median(image.data[:, :, 0], axis=0), 1)[0]
    slope_after = np.polyfit(np.arange(256), np.median(output, axis=0), 1)[0]
    assert slope_after == pytest.approx(slope_before, rel=0.02)


def test_list_mode_touches_only_the_listed_columns(tmp_path):
    """This is the conservative mode: it does what it was told, and nothing else."""
    image, _ = striped_field()
    target = tmp_path / "defects.json"
    detection = get("LinearDefectDetection")(output_path=str(target))
    detection.execute_on_image(image)
    listed = sorted({d["index"] for d in detection.result["defects"]})

    output = get("LinearPatternSubtraction")(
        mode="defect_list", defects_path=str(target)).execute_on_image(image).data[:, :, 0]

    modified = np.where(np.abs(output - image.data[:, :, 0]).max(axis=0) > 1e-7)[0]
    assert sorted(modified.tolist()) == listed


def test_list_mode_requires_a_list():
    image, _ = striped_field(size=64)

    with pytest.raises(ValueError, match="defects_path"):
        get("LinearPatternSubtraction")(mode="defect_list").execute_on_image(image)


def test_a_missing_list_says_so(tmp_path):
    image, _ = striped_field(size=64)

    with pytest.raises(ValueError, match="not found"):
        get("LinearPatternSubtraction")(
            mode="defect_list", defects_path=str(tmp_path / "nothing.json")
        ).execute_on_image(image)


def test_cfa_mode_preserves_the_mosaic():
    """Without it, correcting the offset between Bayer sites would erase the colour
    information."""
    rng = np.random.default_rng(4)
    mosaic = np.full((256, 256), 0.10)
    mosaic[:, 0::2] += 0.05
    mosaic = mosaic + rng.normal(0, 0.002, (256, 256))
    image = Image(mosaic[:, :, None].astype(np.float32))

    with_cfa = get("LinearPatternSubtraction")(cfa=True).execute_on_image(image).data[:, :, 0]
    without_cfa = get("LinearPatternSubtraction")(cfa=False).execute_on_image(image).data[:, :, 0]

    deviation = lambda p: abs(p[:, 0::2].mean() - p[:, 1::2].mean())  # noqa: E731
    assert deviation(with_cfa) == pytest.approx(0.05, abs=0.002)
    assert deviation(without_cfa) < deviation(with_cfa)


def test_rows_are_corrected_too():
    rng = np.random.default_rng(6)
    data = np.full((256, 256), 0.10) + rng.normal(0, 0.003, (256, 256))
    data[[40, 120, 200], :] += 0.03
    image = Image(data[:, :, None].astype(np.float32))

    output = get("LinearPatternSubtraction")(columns=False,
                                             rows=True).execute_on_image(image).data[:, :, 0]

    residual = np.median(output, axis=1) - 0.10
    assert np.abs(residual[[40, 120, 200]]).max() < 0.002


# --- the pipeline step ----------------------------------------------------------------

def inventory(tmp_path):
    from retina.io.fits import save_fits
    from retina.pipeline import scan

    rng = np.random.default_rng(0)
    for kind, count in (("LIGHT", 4), ("BIAS", 3)):
        for i in range(count):
            save_fits(str(tmp_path / f"{kind.lower()}_{i}.fits"),
                      Image(rng.uniform(0.1, 0.2, (32, 32, 1)).astype(np.float32)),
                      {"IMAGETYP": kind, "EXPTIME": 10.0 if kind == "LIGHT" else 0.0,
                       "FILTER": "L"})
    return scan(str(tmp_path))


def calibration_recipe(inv, preset):
    from retina.pipeline import plan

    step = next(s for s in plan(inv, preset=preset).steps if s.id.startswith("calibrate_"))
    return [p.process_id for p in step.recipe.processes], step


def test_the_lps_step_is_absent_by_default(tmp_path):
    from retina.pipeline import Preset

    names, _ = calibration_recipe(inventory(tmp_path), Preset())

    assert "LinearPatternSubtraction" not in names


@pytest.mark.parametrize("debayer", [False, True])
def test_the_lps_step_comes_before_the_debayer(tmp_path, debayer):
    """The order is not a matter of taste: once debayered, interpolation has mixed the pattern
    across colours and it is no longer separable."""
    from retina.pipeline import Preset

    names, step = calibration_recipe(inventory(tmp_path),
                                     Preset(lps=True, debayer=debayer))

    assert "LinearPatternSubtraction" in names
    assert names.index("LinearPatternSubtraction") > names.index("CosmeticCorrection")
    if debayer:
        assert names.index("LinearPatternSubtraction") < names.index("Debayer")
    # The CFA flag follows the presence of an **upcoming** debayer.
    lps = next(p for p in step.recipe.processes
               if p.process_id == "LinearPatternSubtraction")
    assert lps.cfa is debayer


def test_the_lps_step_survives_plan_serialisation(tmp_path):
    from retina.pipeline import Plan, Preset, plan

    origin = plan(inventory(tmp_path), preset=Preset(lps=True))

    replayed = Plan.from_dict(origin.to_dict())

    step = next(s for s in replayed.steps if s.id.startswith("calibrate_"))
    assert "LinearPatternSubtraction" in [p.process_id for p in step.recipe.processes]
