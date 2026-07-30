"""Run cache: never redo what is still right, redo everything the moment it changes."""

from __future__ import annotations

import os

import pytest
from retina.pipeline import plan, scan
from retina.pipeline.cache import clear, fingerprint, is_fresh, manifest_path
from retina.pipeline.presets import Preset
from retina.pipeline.runner import run

FAST = Preset(name="fast", measure=False, register=False)


@pytest.fixture
def prepare(raws_mono, tmp_path):
    """A short plan, already run once, on a brand new output folder."""
    p = plan(scan(raws_mono), FAST, output_dir=str(tmp_path / "out"))
    return p, run(p)


def test_a_second_run_recomputes_nothing(prepare):
    p, first = prepare
    second = run(p)

    assert first.skipped == []
    assert second.executed == []
    assert set(second.skipped) == {s.id for s in p.steps}


def test_force_ignores_the_cache(prepare):
    p, _ = prepare
    report = run(p, force=True)

    assert report.skipped == []
    assert len(report.executed) == len(p.steps)


def test_a_changed_parameter_invalidates_the_step_and_its_downstream(prepare):
    """Changing a rejection threshold redoes the integration — and its dependents, nothing else."""
    p, _ = prepare
    p.step("integrate_light_L_5s_bin1_g120_m10C").process.sigma_high = 1.5
    report = run(p)

    assert report.executed == ["integrate_light_L_5s_bin1_g120_m10C",
                                "autocrop_light_L_5s_bin1_g120_m10C"]
    # the R group, for its part, is not concerned
    assert not any("_R_" in e for e in report.executed)


def test_a_changed_input_invalidates_the_step(prepare, tmp_path):
    p, _ = prepare
    step = p.step("master_bias_bin1_g120_m10C")
    os.utime(step.inputs[0], None)  # same content, new timestamp

    assert not is_fresh(step)


def test_a_deleted_output_invalidates_the_step(prepare):
    p, _ = prepare
    step = p.step("master_bias_bin1_g120_m10C")
    os.remove(step.outputs[0])

    assert not is_fresh(step)
    assert "master_bias_bin1_g120_m10C" in run(p).executed


def test_a_deleted_manifest_invalidates_the_step(prepare):
    p, _ = prepare
    step = p.step("master_bias_bin1_g120_m10C")
    os.remove(manifest_path(step.outputs[0]))

    assert not is_fresh(step)


def test_a_corrupt_manifest_does_not_crash(prepare):
    p, _ = prepare
    step = p.step("master_bias_bin1_g120_m10C")
    with open(manifest_path(step.outputs[0]), "w", encoding="utf-8") as fh:
        fh.write("{ not json")

    assert not is_fresh(step)


def test_the_fingerprint_depends_on_the_late_bindings(prepare):
    """Changing the reference frame must invalidate the registrations."""
    p, _ = prepare
    step = p.step("master_bias_bin1_g120_m10C")

    assert fingerprint(step, {"reference_path": "/a.fits"}) \
        != fingerprint(step, {"reference_path": "/b.fits"})


def test_the_fingerprint_is_stable_under_identical_conditions(prepare):
    p, _ = prepare
    step = p.step("master_bias_bin1_g120_m10C")

    assert fingerprint(step) == fingerprint(step)


def test_the_measurements_are_cached(raws_mono, tmp_path):
    """Detecting the stars of a hundred frames is the dominant cost of a second run."""
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path))
    first = run(p)
    second = run(p)

    assert second.executed == []
    # and the measurements read back from disk are enough to find the same reference
    assert second.reference == first.reference
    assert second.measurements.keys() == first.measurements.keys()


def test_clearing_the_cache_forces_a_recompute(prepare):
    p, _ = prepare
    cleared = clear(p.output_dir)

    assert cleared == sum(len(s.outputs) for s in p.steps)
    assert len(run(p).executed) == len(p.steps)


def test_the_manifest_is_written_after_the_output(prepare):
    """The order guarantees that an interruption never leaves a cache both valid and wrong."""
    p, _ = prepare
    for step in p.steps:
        for output in step.outputs:
            assert os.path.getmtime(manifest_path(output)) >= os.path.getmtime(output)
