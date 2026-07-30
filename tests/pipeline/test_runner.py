"""Running a plan: correctness of the result, progress, cancellation.

The assertions bear on the **ground truth** of the synthetic dataset (bias level, dark
current, vignetting, hot pixels, dithering): that is what tells a pipeline producing files
apart from a pipeline producing the right ones.
"""

from __future__ import annotations

import itertools
import os

import numpy as np
import pytest
from retina.io.fits import load_fits
from retina.pipeline import plan, scan
from retina.pipeline.presets import Preset
from retina.pipeline.runner import run
from retina.pipeline.synthetic import DITHER, HOT_PIXELS, SKY_LEVEL, truth
from retina.process import context
from retina.process.progress import ProcessCancelled, ProgressMonitor


@pytest.fixture(scope="module")
def execute(tmp_path_factory, request):
    """Run the mono pipeline once and return (plan, report) — this is the slow test."""
    raws = request.getfixturevalue("raws_mono")
    output = str(tmp_path_factory.mktemp("run_mono"))
    p = plan(scan(raws), "auto", output_dir=output)
    return p, run(p)


def data(path: str) -> np.ndarray:
    return load_fits(path)[0].data


# --- calibration correctness ---------------------------------------------------------

def test_the_master_bias_recovers_the_injected_level(execute):
    _, report = execute

    assert np.median(data(report.outputs["master_bias_bin1_g120_m10C"])) == pytest.approx(
        truth()["bias_level"], abs=2e-3)


def test_the_master_dark_carries_the_bias_and_the_current(execute):
    _, report = execute

    assert np.median(data(report.outputs["master_dark_5s_bin1_g120_m10C"])) == pytest.approx(
        truth()["dark_level"], abs=2e-3)


def test_calibration_removes_the_hot_pixels(execute):
    """The dark carries them; the cosmetic correction finishes the job."""
    p, _ = execute
    step = p.step("calibrate_light_L_5s_bin1_g120_m10C")
    raw_data = data(step.inputs[0])
    calibrated = data(step.outputs[0])

    hot_before = np.median([raw_data[y, x, 0] for y, x in HOT_PIXELS])
    hot_after = np.median([calibrated[y, x, 0] for y, x in HOT_PIXELS])

    assert hot_before > 0.4
    assert hot_after == pytest.approx(float(np.median(calibrated)), abs=5e-3)


def test_calibration_flattens_the_vignetting(execute):
    p, _ = execute
    step = p.step("calibrate_light_L_5s_bin1_g120_m10C")
    raw_data, calibrated = data(step.inputs[0]), data(step.outputs[0])

    def dip(image):
        return abs(float(np.median(image[:20, :20])) - float(np.median(image[54:74, 54:74])))

    assert dip(calibrated) < dip(raw_data) / 4


def test_the_calibrated_background_equals_the_injected_sky(execute):
    p, _ = execute
    calibrated = data(p.step("calibrate_light_L_5s_bin1_g120_m10C").outputs[0])
    expected = SKY_LEVEL * float(truth()["vignette_map"].mean())

    assert float(np.median(calibrated)) == pytest.approx(expected, abs=5e-3)


# --- registration and integration ----------------------------------------------------

def test_registration_makes_up_for_the_dithering(execute):
    """Without registration the stars smear out: the peak of the stack collapses."""
    p, report = execute
    integrated = data(report.outputs["integrate_light_L_5s_bin1_g120_m10C"])
    unregistered = np.mean(
        [data(f) for f in p.step("calibrate_light_L_5s_bin1_g120_m10C").outputs], axis=0)

    assert ((0, 0),) * len(DITHER) != DITHER      # the dataset really does shift the frames
    assert integrated.max() > unregistered.max() * 1.5


def test_the_pipeline_produces_one_integration_per_filter(execute):
    _, report = execute

    assert sorted(os.path.basename(r) for r in report.results) == [
        "light_L_5s_bin1_g120_m10C_crop.fits", "light_R_5s_bin1_g120_m10C_crop.fits"]
    assert all(os.path.exists(r) for r in report.results)


def test_the_keywords_survive_the_chain(execute):
    """The filter and the exposure must follow: a later run groups on them."""
    p, _ = execute
    _, keywords = load_fits(p.step("calibrate_light_L_5s_bin1_g120_m10C").outputs[0])

    assert keywords["FILTER"] == "L"
    assert keywords["EXPTIME"] == 5.0
    assert "retina.pipeline" in str(keywords.get("HISTORY", ""))


def test_the_reference_is_shared_by_every_group(execute):
    """Otherwise the L and R layers would not line up at composition time."""
    p, report = execute
    references = {s.processes[0].reference_path
                  for s in p.steps if s.id.startswith("register_")}

    assert len(references) == 1
    assert references == {report.reference}


def test_the_reference_maximizes_the_star_count(execute):
    """The criterion: what you want from a reference is landmarks to pair up."""
    _, report = execute
    all_measures = [m for measures in report.measurements.values() for m in measures]
    chosen = next(m for m in all_measures if m["frame"] == report.reference)

    assert chosen["stars"] == max(m["stars"] for m in all_measures)


def test_the_measurement_weights_reach_the_integration(execute):
    p, report = execute
    integration = p.step("integrate_light_L_5s_bin1_g120_m10C").process
    measures = report.measurements["light_L_5s_bin1_g120_m10C"]

    assert len(integration.weights) == len(measures)
    assert integration.weights == pytest.approx([m["weight"] for m in measures])


# --- OSC ------------------------------------------------------------------------------

def test_the_osc_pipeline_debayers(raws_osc, tmp_path):
    p = plan(scan(raws_osc), "auto", output_dir=str(tmp_path))
    report = run(p)

    integrated = data(report.results[0])
    assert integrated.shape[2] == 3                     # RGB after debayering
    assert integrated[:, :, 0].mean() > integrated[:, :, 2].mean()  # injected R gain > B gain


# --- progress and cancellation --------------------------------------------------------

def test_progress_is_monotonic_and_bounded(raws_mono, tmp_path):
    views: list[float] = []
    p = plan(scan(raws_mono), Preset(name="short", measure=False, register=False),
             output_dir=str(tmp_path))
    run(p, on_progress=lambda f, m: views.append(f))

    assert views and all(0.0 <= f <= 1.0 for f in views)
    assert all(b >= a - 1e-9 for a, b in itertools.pairwise(views))
    assert views[-1] == pytest.approx(1.0)


def test_the_messages_name_the_step_and_the_frame(raws_mono, tmp_path):
    messages: list[str] = []
    p = plan(scan(raws_mono), Preset(name="short", measure=False, register=False),
             output_dir=str(tmp_path))
    run(p, on_progress=lambda f, m: messages.append(m))

    assert any("frame 1/3" in m for m in messages)
    assert any("Master bias" in m for m in messages)


def test_cancelling_interrupts_and_leaves_nothing_behind(raws_mono, tmp_path):
    """A truncated file would be worse than a missing one: the cache would believe it valid."""
    monitor = ProgressMonitor()
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path))

    context.set_monitor(monitor)
    try:
        with pytest.raises(ProcessCancelled):
            run(p, on_progress=lambda f, m: monitor.cancel() if f and f > 0.2 else None)
    finally:
        context.set_monitor(None)

    partials = [f for _, _, names in os.walk(tmp_path) for f in names if f.endswith(".part")]
    assert partials == []
    assert not os.path.exists(p.step("integrate_light_L_5s_bin1_g120_m10C").outputs[0])


def test_an_already_installed_monitor_is_reused(raws_mono, tmp_path):
    """This is what carries cancellation from the interface all the way down here."""
    monitor = ProgressMonitor()
    received: list[float] = []
    monitor.on_progress = lambda f, m: received.append(f)
    p = plan(scan(raws_mono), Preset(name="short", measure=False, register=False),
             output_dir=str(tmp_path))

    context.set_monitor(monitor)
    try:
        run(p)
    finally:
        context.set_monitor(None)

    assert received and received[-1] == pytest.approx(1.0)


# --- robustness -----------------------------------------------------------------------

def test_without_masters_the_lights_go_through_raw(tmp_path):
    """A folder of lights alone must still produce an integration, with an explicit note."""
    from retina.pipeline.synthetic import make_dataset

    source = tmp_path / "lights"
    source.mkdir()
    make_dataset(str(source), "mono", filters=("L",))
    for name in os.listdir(source):
        if not name.startswith("light"):
            os.remove(source / name)

    p = plan(scan(str(source)), "auto", output_dir=str(tmp_path / "out"))
    report = run(p)

    assert len(report.results) == 1
    assert any("lights used raw" in n for n in report.notes)


def test_the_report_is_serializable(execute):
    _, report = execute
    data = report.to_dict()

    assert data["reference"] == report.reference
    assert data["results"] == report.results
    assert set(data["measurements"]) == set(report.measurements)


def test_the_integration_inherits_the_keywords_of_its_frames(execute):
    """A final image without exposure or filter cannot be checked and cannot be filed."""
    _, report = execute
    _, keywords = load_fits(report.outputs["integrate_light_L_5s_bin1_g120_m10C"])

    assert keywords["FILTER"] == "L"
    assert keywords["EXPTIME"] == 5.0
    assert keywords["GAIN"] == 120.0
    assert keywords["INSTRUME"] == "Retina Synthetic"


def test_the_crop_preserves_the_keywords(execute):
    """The crop is the last step: its file is the one we deliver."""
    _, report = execute
    _, keywords = load_fits(report.results[0])

    assert keywords["FILTER"] in ("L", "R")
    assert keywords["EXPTIME"] == 5.0
