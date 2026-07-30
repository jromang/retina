"""Frame selection: rejecting by hand without paying for the measurement twice.

The sensitive point is not that a reject sets a weight to zero — it is that it must **not**
restart star detection. A batch of a hundred frames takes minutes to measure; dropping six
of them should cost one integration, not a second measuring pass. These tests check both
sides: the reject acts, and the cache holds.
"""

from __future__ import annotations

import json
import os

import pytest
from retina.pipeline import plan, scan, selection
from retina.pipeline.runner import run
from retina.processes.subframe import SubframeSelector


@pytest.fixture(scope="module")
def execute(tmp_path_factory, request):
    """A full run of the mono set — plan and report, reused across the whole module."""
    raws = request.getfixturevalue("raws_mono")
    output = str(tmp_path_factory.mktemp("run_selection"))
    p = plan(scan(raws), "auto", output_dir=output)
    return p, run(p)


def _group(p) -> str:
    """The first light group measured by the plan."""
    groups = sorted(selection.measure_steps(p))
    assert groups, "the auto preset must lay down a measurement step"
    return groups[0]


# --- evaluation, independently of any file ------------------------------------------

def _measurements(n: int = 5) -> list[dict]:
    """Synthetic measurements: frame i is better the larger i is."""
    return [{"frame": f"/data/light_{i:03d}.fits", "stars": 100 + i, "fwhm": 5.0 - 0.2 * i,
             "eccentricity": 0.5 - 0.05 * i, "noise": 1e-3, "snr": 10.0 + i,
             "median": 0.01} for i in range(n)]


def test_a_manual_reject_zeroes_the_weight_without_erasing_the_row():
    """The downstream mechanism already exists: approved false ⇒ zero weight ⇒ not stacked.

    But the frame must **stay visible** in the report, with its reason: vanishing silently
    from a table is exactly what we hold against the reference implementations.
    """
    rows = _measurements()
    selector = SubframeSelector(manual_rejects=["/data/light_002.fits"])

    selector.evaluate(rows)

    assert len(rows) == 5
    assert rows[2]["approved"] is False
    assert rows[2]["rejected_by"] == "manual"
    assert rows[2]["weight"] == 0.0
    assert sum(r["weight"] for r in rows) == pytest.approx(1.0)


def test_a_reject_is_designated_by_path_not_by_rank():
    """A frame lost along the way shifts the ranks; the path, on the other hand, holds."""
    rows = _measurements()
    del rows[1]  # calibration could not produce this one
    selector = SubframeSelector(manual_rejects=["/data/light_003.fits"])

    selector.evaluate(rows)

    rejected_items = [r["frame"] for r in rows if not r["approved"]]
    assert rejected_items == ["/data/light_003.fits"]


def test_a_frame_dropped_by_the_expression_says_why():
    """`rejected_by` only ever applied to min_weight: the expression stayed silent."""
    rows = _measurements()
    selector = SubframeSelector(approval="stars > 101", min_weight=0.0)

    selector.evaluate(rows)

    assert [r.get("rejected_by") for r in rows[:2]] == ["expression", "expression"]
    assert rows[4].get("rejected_by") is None


def test_re_evaluation_does_not_keep_a_stale_reason():
    """Rejudging must start from the raw measurements, otherwise a lifted reject stays shown."""
    rows = _measurements()
    selector = SubframeSelector(manual_rejects=["/data/light_002.fits"])
    selector.evaluate(rows)

    selector.manual_rejects = []
    selector.evaluate(rows)

    assert all(r["approved"] for r in rows)
    assert all("rejected_by" not in r for r in rows)


def test_a_manual_reject_wins_over_the_automatic_criterion():
    """Two possible reasons: show the one the user set themselves."""
    rows = _measurements()
    selector = SubframeSelector(approval="stars > 101", manual_rejects=[rows[0]["frame"]])

    selector.evaluate(rows)

    assert rows[0]["rejected_by"] == "manual"


# --- the cache: the whole reason for the decoupling ----------------------------------

def test_the_criteria_do_not_count_in_the_cache_fingerprint():
    """`cache_values` isolates what decides the measurement file that gets produced."""
    detection = SubframeSelector(frames=["/a.fits"], fwhm=3.0).cache_values()
    judgement = SubframeSelector(frames=["/a.fits"], fwhm=3.0, approval="snr > 3",
                                 manual_rejects=["/a.fits"], min_weight=0.2).cache_values()

    assert detection == judgement
    assert "manual_rejects" not in detection
    assert detection["fwhm"] == 3.0  # the detection settings, on the other hand, are there


def test_changing_the_detection_does_invalidate_the_cache():
    """The flip side: whatever changes the measurements must always have them redone."""
    a = SubframeSelector(frames=["/a.fits"], fwhm=3.0).cache_values()
    b = SubframeSelector(frames=["/a.fits"], fwhm=4.0).cache_values()

    assert a != b


def test_a_reject_does_not_remeasure_but_does_reintegrate(execute):
    """The test that justifies the whole thing: rejecting costs one integration, not a
    hundred measurements."""
    p, _ = execute
    group = _group(p)
    measures = selection.measures(p)[group]
    assert measures, "the run must have produced measurements"

    selection.set_rejects(p, group, [measures[0]["frame"]])
    report = run(p)

    assert f"measure_{group}" in report.skipped, "the measurements should have been reused"
    assert f"integrate_{group}" in report.executed, "the integration should have been redone"


def test_the_second_run_rejudges_the_measurements_read_back(execute):
    """The current criteria must produce the weights, not the ones frozen in the JSON."""
    p, _ = execute
    group = _group(p)
    target = selection.measures(p)[group][0]["frame"]

    selection.set_rejects(p, group, [target])
    report = run(p)

    reread = report.measurements[group]
    rejected = next(m for m in reread if m["frame"] == target)
    assert rejected["approved"] is False
    assert rejected["rejected_by"] == "manual"
    assert rejected["weight"] == 0.0


def test_the_rejects_survive_the_serialization_of_the_plan(execute, tmp_path):
    """A plan must stay replayable identically — and the rejects are part of it."""
    p, _ = execute
    group = _group(p)
    target = selection.measures(p)[group][0]["frame"]
    selection.set_rejects(p, group, [target])

    path = str(tmp_path / "plan.json")
    p.save(path)
    from retina.pipeline.plan import Plan

    assert selection.rejects(Plan.load(path))[group] == [target]


# --- reading measurements back, and cumulative exposure ------------------------------

def test_the_measurements_are_read_back_without_executing_anything(execute):
    p, _ = execute
    group = _group(p)

    measures = selection.measures(p)

    assert set(measures) == set(selection.measure_steps(p))
    assert all("weight" in m and "frame" in m for m in measures[group])
    path = selection.measures_path(p, group)
    assert path and os.path.exists(path)
    with open(path, encoding="utf-8") as fh:
        assert json.load(fh)


def test_a_group_never_measured_returns_an_empty_list(raws_mono, tmp_path):
    """Inspecting a plan before launching it is a normal case, not an error."""
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path / "empty"))

    assert not selection.has_measures(p)
    assert all(rows == [] for rows in selection.measures(p).values())


def test_the_cumulative_exposure_in_the_report_accounts_for_rejects(execute):
    """The plan's figure is an upper bound; the report's has to be the real one."""
    p, _ = execute
    group = _group(p)
    selection.set_rejects(p, group, [selection.measures(p)[group][0]["frame"]])
    report = run(p)

    summary = next(b for b in report.products if b["key"] == group)
    expected = next(pr for pr in p.products if pr.key == group)

    assert summary["rejected"] == 1
    assert summary["frames"] == expected.frames - 1
    assert summary["rejected_by"] == {"manual": 1}
    if expected.exposure is not None:
        assert summary["integration"] == pytest.approx(summary["frames"] * expected.exposure)


def test_set_rejects_refuses_an_unknown_group(execute):
    p, _ = execute

    with pytest.raises(KeyError, match="No measurement step"):
        selection.set_rejects(p, "group_that_does_not_exist", [])


# --- criteria ------------------------------------------------------------------------

def test_the_criteria_apply_to_every_group_by_default(execute):
    """An FWHM threshold makes no sense filter by filter — the reference tools have the same
    single button."""
    p, _ = execute

    selection.set_criteria(p, approval="eccentricity < 0.9")

    frames = selection.criteria(p)
    assert frames, "the plan must have at least one measured group"
    assert all(c["approval"] == "eccentricity < 0.9" for c in frames.values())


def test_an_unknown_criterion_raises_rather_than_being_ignored(execute):
    p, _ = execute

    with pytest.raises(ValueError, match="Unknown criteria"):
        selection.set_criteria(p, fwhm_max=3.0)


def test_changing_an_expression_does_not_trigger_a_remeasure(execute):
    """The three judgement criteria stay out of the cache fingerprint."""
    p, _ = execute
    group = _group(p)

    selection.set_criteria(p, min_weight=0.5)
    report = run(p)

    assert f"measure_{group}" in report.skipped


def test_changing_the_roundness_tolerance_triggers_a_remeasure(execute):
    """The flip side: that one is a detection setting, so it changes the measurements."""
    p, _ = execute
    group = _group(p)

    selection.set_criteria(p, roundness_limit=5.0)
    report = run(p)

    assert f"measure_{group}" in report.executed


# --- quantities derived from the batch -----------------------------------------------
#
# `_n` is a min-max: a single outlier flattens it. That is precisely the flaw we cannot live
# with when *dropping* a botched frame — hence `_sigma`, the deviation from the median in
# robust dispersion, a convention taken from the reference tools' `FWHMSigma` variables.

def test_sigma_is_the_deviation_from_the_median_in_robust_dispersion():
    rows = [{"frame": f"/f{i}.fits", "stars": 100, "fwhm": f, "eccentricity": 0.3,
             "noise": 1e-3, "snr": 20.0, "median": 0.01}
            for i, f in enumerate([3.0, 3.1, 3.2, 3.0, 3.1])]

    SubframeSelector().evaluate(rows)

    assert rows[0]["fwhm_median"] == pytest.approx(3.1)
    assert rows[2]["fwhm_sigma"] > 0  # above the median
    assert rows[0]["fwhm_sigma"] < 0  # below it


def test_a_botched_frame_flattens_the_min_max_but_not_the_sigma():
    """The test that justifies the addition: this is the use case, not an edge case.

    A homogeneous batch plus one frame whose tracking ran away. In min-max, every good frame
    piles up against 1 and they become indistinguishable — the ranking loses its resolution
    exactly where we need it. In sigma, the botched one lands far out and the others keep
    their spread.
    """
    fwhms = [3.0, 3.1, 3.2, 3.0, 20.0]
    rows = [{"frame": f"/f{i}.fits", "stars": 100, "fwhm": f, "eccentricity": 0.3,
             "noise": 1e-3, "snr": 20.0, "median": 0.01} for i, f in enumerate(fwhms)]

    SubframeSelector().evaluate(rows)

    good_n = [r["fwhm_n"] for r in rows[:4]]
    assert max(good_n) - min(good_n) < 0.02, "the min-max does pile up the good frames"
    assert rows[4]["fwhm_sigma"] > 10, "the botched one must stand well clear"
    good_sigma = [r["fwhm_sigma"] for r in rows[:4]]
    assert max(good_sigma) - min(good_sigma) > 1.0, "the good ones stay distinguishable"


def test_a_perfectly_homogeneous_batch_yields_a_zero_sigma():
    """Zero dispersion: nobody deviates from anybody, and above all nothing gets divided."""
    rows = [{"frame": f"/f{i}.fits", "stars": 100, "fwhm": 3.0, "eccentricity": 0.3,
             "noise": 1e-3, "snr": 20.0, "median": 0.01} for i in range(4)]

    SubframeSelector().evaluate(rows)

    assert all(r["fwhm_sigma"] == 0.0 for r in rows)


def test_the_expressions_can_use_the_derived_quantities(execute):
    rows = [{"frame": f"/f{i}.fits", "stars": 100, "fwhm": f, "eccentricity": 0.3,
             "noise": 1e-3, "snr": 20.0, "median": 0.01}
            for i, f in enumerate([3.0, 3.1, 3.0, 12.0])]

    SubframeSelector(approval="fwhm_sigma < 3", min_weight=0.0).evaluate(rows)

    assert [r["approved"] for r in rows] == [True, True, True, False]
    assert rows[3]["rejected_by"] == "expression"


# --- validation of the expressions ---------------------------------------------------

def test_a_faulty_expression_is_refused_before_it_enters_the_plan(execute):
    """Once stored, it would make any read-back of the measurements impossible."""
    p, _ = execute

    before = selection.criteria(p)

    with pytest.raises(ValueError, match="approval"):
        selection.set_criteria(p, approval="fwhm << 3")

    assert selection.criteria(p) == before, "the plan must be left intact"


def test_an_unknown_variable_name_is_reported(execute):
    p, _ = execute

    with pytest.raises(ValueError, match="approval"):
        selection.set_criteria(p, approval="fwhmm < 3")


def test_an_empty_expression_stays_valid(execute):
    p, _ = execute

    selection.set_criteria(p, approval="", weighting="")

    assert selection.criteria(p)
