"""``pipeline.*`` family: the wizard is nothing but a client of the scriptable API.

The contract checked here: ``scan`` and ``plan`` return their result directly, ``run``
returns a job id and works in the background, every call emits the equivalent Python echo,
and a cancellation leaves no truncated output behind it.
"""

from __future__ import annotations

import asyncio
import itertools
import os

import pytest
from rpcsession import RpcFailure

pytest.importorskip("astropy")


@pytest.fixture
def raws(tmp_path):
    from retina.pipeline.synthetic import make_dataset

    root = tmp_path / "raws"
    root.mkdir()
    make_dataset(str(root), "mono", filters=("L",))
    return str(root)


#: notifications that close a pipeline job, whatever its fate
_ENDINGS = ("job.done", "job.error", "job.cancelled")


async def _wait(session, timeout: float = 60.0) -> dict:
    """Wait for the pipeline job's terminal notification, and **consume** it.

    Removing it is not cosmetic. ``Session.of()`` replays the whole history of received
    notifications: without a purge, a test that launches two runs would see, on its second
    call, the ``job.done`` of the **first**, return at once, and judge the second run on the
    first one's report. That is a false result both ways -- a broken cache would go unnoticed,
    and a correct cache looked broken here.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await session.drain(0.1)
        for method in _ENDINGS:
            events = session.of(method)
            if events:
                session.notifications[:] = [
                    n for n in session.notifications if n.get("method") not in _ENDINGS
                ]
                return {"method": method, **events[-1]}
    raise AssertionError("the pipeline job never finished")


# --- scan ---------------------------------------------------------------------------------

async def test_the_scan_returns_the_inventory(session, raws):
    inventory = await session.call("pipeline.scan", path=raws)

    assert inventory["root"] == os.path.abspath(raws)
    assert len(inventory["frames"]) == 13
    assert {f["kind"] for f in inventory["frames"]} == {"light", "dark", "flat", "bias"}


async def test_the_scan_echoes_its_python_equivalent(session, raws):
    await session.call("pipeline.scan", path=raws)
    await session.drain()

    assert any("retina.pipeline.scan(" in p["code"] for p in session.of("echo"))


async def test_a_missing_folder_returns_a_domain_error(session):
    with pytest.raises(RpcFailure) as exc:
        await session.call("pipeline.scan", path="/does/not/exist")

    assert exc.value.code == -32000


# --- survey -------------------------------------------------------------------------------

async def test_the_survey_returns_the_domain_groups(session, raws):
    """The keys on display must be the plan's own, not a frontend approximation."""
    inventory = await session.call("pipeline.scan", path=raws)
    state = await session.call("pipeline.survey", inventory=inventory)

    keys = {g["key"] for g in state["groups"]}
    assert "light_L_5s_bin1_g120_m10C" in keys
    assert keys == set(state["matches"]) | {
        g["key"] for g in state["groups"] if g["kind"] in ("dark", "bias")
    }


async def test_the_survey_reports_the_matched_masters(session, raws):
    inventory = await session.call("pipeline.scan", path=raws)
    state = await session.call("pipeline.survey", inventory=inventory)

    match = state["matches"]["light_L_5s_bin1_g120_m10C"]
    assert match["dark"] is not None
    assert match["flat"] is not None


async def test_the_survey_groups_feed_back_into_the_plan(session, raws,
                                                         tmp_path):
    """The full round-trip: what the wizard displays is what it can have executed."""
    inventory = await session.call("pipeline.scan", path=raws)
    state = await session.call("pipeline.survey", inventory=inventory)

    plan = await session.call("pipeline.plan", inventory=inventory, preset="auto",
                              output_dir=str(tmp_path / "out"), groups=state["groups"])

    assert any(s["id"] == "master_bias_bin1_g120_m10C" for s in plan["steps"])


# --- inventory corrections ----------------------------------------------------------------
#
# The wizard shows a "?" column on guessed frames: the doubt has to be liftable. The
# inventory lives on the client, which passes it back corrected; the server keeps nothing --
# but the operation still goes through the domain, so that it gets echoed.

async def test_reclassify_fixes_the_kind_and_the_source(session, raws):
    inventory = await session.call("pipeline.scan", path=raws)
    target = next(f["path"] for f in inventory["frames"] if f["kind"] == "light")

    corrected = await session.call("pipeline.reclassify", inventory=inventory,
                                 paths=[target], kind="flat")

    touched = next(f for f in corrected["frames"] if f["path"] == target)
    assert (touched["kind"], touched["source"]) == ("flat", "user")


async def test_reclassify_echoes_its_python_equivalent(session, raws):
    inventory = await session.call("pipeline.scan", path=raws)
    target = inventory["frames"][0]["path"]
    session.clear()
    await session.call("pipeline.reclassify", inventory=inventory, paths=[target],
                       kind="dark")
    await session.drain()

    codes = [p["code"] for p in session.of("echo")]
    assert any(f"retina.pipeline.reclassify(inventory, [{target!r}], 'dark')" in c
               for c in codes)


async def test_excluding_drops_the_frame_from_the_plan(session, raws, tmp_path):
    """An excluded frame must stop weighing on the masters, not merely disappear."""
    inventory = await session.call("pipeline.scan", path=raws)
    biases = [f["path"] for f in inventory["frames"] if f["kind"] == "bias"]

    corrected = await session.call("pipeline.exclude", inventory=inventory,
                                 paths=biases[:1], excluded=True)
    plan = await session.call("pipeline.plan", inventory=corrected, preset="auto",
                              output_dir=str(tmp_path / "out"))

    master = next(s for s in plan["steps"] if s["id"].startswith("master_bias"))
    assert len(master["inputs"]) == len(biases) - 1


async def test_excluding_then_reinstating_echoes_both_gestures(session, raws):
    inventory = await session.call("pipeline.scan", path=raws)
    target = inventory["frames"][0]["path"]
    session.clear()

    corrected = await session.call("pipeline.exclude", inventory=inventory, paths=[target])
    rendered = await session.call("pipeline.exclude", inventory=corrected, paths=[target],
                               excluded=False)
    await session.drain()

    assert not next(f for f in rendered["frames"] if f["path"] == target)["excluded"]
    codes = [p["code"] for p in session.of("echo")]
    assert any("retina.pipeline.exclude(inventory, [" in c and "excluded=False" not in c
               for c in codes)
    assert any("excluded=False)" in c for c in codes)


async def test_a_frame_absent_from_the_inventory_returns_a_domain_error(session, raws):
    inventory = await session.call("pipeline.scan", path=raws)

    with pytest.raises(RpcFailure) as exc:
        await session.call("pipeline.reclassify", inventory=inventory,
                           paths=["/nowhere/at/all.fits"], kind="dark")

    assert exc.value.code == -32000


# --- plan ---------------------------------------------------------------------------------

async def test_the_plan_accepts_a_corrected_grouping(session, raws, tmp_path):
    """Automatic grouping must be replaceable -- and the echo must say so."""
    inventory = await session.call("pipeline.scan", path=raws)
    from retina.pipeline.groups import group_frames
    from retina.pipeline.scan import Inventory

    batches = group_frames(Inventory.from_dict(inventory).frames)
    without_flats = [g.to_dict() for g in batches if g.kind != "flat"]
    session.clear()

    plan = await session.call("pipeline.plan", inventory=inventory, preset="auto",
                              output_dir=str(tmp_path / "out"), groups=without_flats)
    await session.drain()

    assert not any(s["id"].startswith("master_flat") for s in plan["steps"])
    codes = [p["code"] for p in session.of("echo")]
    assert any("groups=batches" in c for c in codes)


async def test_the_plan_is_built_and_serialized(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory, preset="auto",
                              output_dir=str(tmp_path / "out"))

    assert plan["preset"]["name"] == "auto"
    assert [s["id"] for s in plan["steps"]][:2] == [
        "master_bias_bin1_g120_m10C", "master_dark_5s_bin1_g120_m10C"]
    # nothing is written until the run is launched
    assert not os.path.exists(tmp_path / "out")


async def test_the_plan_echoes_its_python_equivalent(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    session.clear()
    await session.call("pipeline.plan", inventory=inventory, preset="mono_lrgb",
                       output_dir=str(tmp_path / "out"))
    await session.drain()

    codes = [p["code"] for p in session.of("echo")]
    assert any("retina.pipeline.plan(inventory, preset='mono_lrgb'" in c for c in codes)


async def test_an_unknown_preset_returns_a_domain_error(session, raws):
    inventory = await session.call("pipeline.scan", path=raws)

    with pytest.raises(RpcFailure) as exc:
        await session.call("pipeline.plan", inventory=inventory, preset="mono_hoo")

    assert exc.value.code == -32000


async def test_the_presets_are_exposed(session):
    presets = await session.call("pipeline.presets")

    assert {p["name"] for p in presets} == {
        "auto", "osc", "mono_lrgb", "mono_sho", "seestar", "dwarf"}
    assert all(p["label"] for p in presets)
    # The labels come from the catalogue: hardcoded, the English interface would display
    # "Automatique". The server pins English in the tests (see conftest).
    assert {p["name"]: p["label"] for p in presets}["auto"] == "Automatic"


# --- run ----------------------------------------------------------------------------------

async def test_the_run_returns_control_immediately(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))

    loop = asyncio.get_running_loop()
    start = loop.time()
    response = await session.call("pipeline.run", plan=plan)

    assert response["job"].startswith("j")
    assert loop.time() - start < 1.0
    await _wait(session)


async def test_the_run_produces_the_integrations_and_its_report(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    await session.call("pipeline.run", plan=plan)
    end = await _wait(session)

    assert end["method"] == "job.done"
    # the report travels with the final notification: no need to ask for it
    assert end["result"]["results"]
    assert all(os.path.exists(p) for p in end["result"]["results"])
    assert end["result"]["reference"]


async def test_the_report_stays_readable_afterwards(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    await session.call("pipeline.run", plan=plan)
    await _wait(session)

    report = await session.call("pipeline.report")
    assert report["results"]
    assert report["executed"]


async def test_the_pipeline_progress_is_determinate(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    await session.call("pipeline.run", plan=plan)
    await _wait(session)

    fractions = [p["fraction"] for p in session.of("job.progress")
                 if p["fraction"] is not None]
    # one ULP of tolerance: nesting the progress windows does floating-point
    # arithmetic, not a bar that goes backwards
    assert all(b >= a - 1e-9 for a, b in itertools.pairwise(fractions))
    assert fractions[-1] == pytest.approx(1.0)
    assert any("frame" in p["message"] for p in session.of("job.progress"))


async def test_the_run_echoes_its_python_equivalent(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    session.clear()
    await session.call("pipeline.run", plan=plan)
    await _wait(session)

    assert any(p["code"] == "retina.pipeline.run(plan)" for p in session.of("echo"))


async def test_an_empty_plan_is_rejected(session):
    with pytest.raises(RpcFailure) as exc:
        await session.call("pipeline.run",
                           plan={"version": "1.0", "root": "/", "output_dir": "/tmp",
                                 "steps": []})

    assert exc.value.code == -32000


async def test_an_invalid_plan_is_rejected(session):
    with pytest.raises(RpcFailure):
        await session.call("pipeline.run", plan={"not": "a plan"})


async def test_the_pipeline_shows_up_in_the_snapshot(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    await session.call("pipeline.run", plan=plan)

    snapshot = await session.call("state.snapshot")
    # possible race on a fast machine: the job may already be over
    if snapshot["jobs"]:
        assert snapshot["jobs"][0]["process_id"] == "Pipeline"
    await _wait(session)


async def test_only_one_preprocessing_run_at_a_time(session, raws, tmp_path):
    """Two runs would write to the same files, and the pool is shared."""
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    await session.call("pipeline.run", plan=plan)
    try:
        with pytest.raises(RpcFailure, match="already in progress"):
            await session.call("pipeline.run", plan=plan)
    finally:
        await _wait(session)


async def test_cancelling_interrupts_and_leaves_nothing_truncated(session, raws,
                                                                  tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    response = await session.call("pipeline.run", plan=plan)
    await session.drain(0.15)
    await session.call("process.cancel", job=response["job"])
    end = await _wait(session)

    assert end["method"] in ("job.cancelled", "job.done")
    partials = [f for _, _, names in os.walk(tmp_path) for f in names if f.endswith(".part")]
    assert partials == []


# --- frame selection ----------------------------------------------------------------------
#
# The selector works **between two runs**: the measurements are on disk, we read them back,
# re-judge, and relaunch. The reference implementation opens a modal in the middle of the run
# and blocks it -- our runner is fire-and-forget, and stays that way.

async def _full_run(session, raws, output: str) -> dict:
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory, preset="auto",
                              output_dir=output)
    await session.call("pipeline.run", plan=plan)
    end = await _wait(session)
    assert end["method"] == "job.done"
    return plan


async def test_the_measurements_are_read_back_after_a_run(session, raws, tmp_path):
    plan = await _full_run(session, raws, str(tmp_path / "out"))

    measures = await session.call("pipeline.measures", plan=plan)

    group = "light_L_5s_bin1_g120_m10C"
    assert group in measures["groups"]
    lines = measures["groups"][group]
    assert lines and all({"frame", "fwhm", "eccentricity", "snr", "stars", "weight",
                           "approved"} <= set(m) for m in lines)
    assert measures["rejects"][group] == []


async def test_a_never_executed_plan_returns_empty_measurements(session, raws, tmp_path):
    """Inspecting before launching is a normal case: no error, just empty lists."""
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "never"))

    measures = await session.call("pipeline.measures", plan=plan)

    assert all(lines == [] for lines in measures["groups"].values())


async def test_a_rejection_zeroes_the_weight_and_shows_in_the_summary(session, raws, tmp_path):
    plan = await _full_run(session, raws, str(tmp_path / "out"))
    group = "light_L_5s_bin1_g120_m10C"
    target = (await session.call("pipeline.measures", plan=plan))["groups"][group][0]["frame"]

    corrected = await session.call("pipeline.set_rejects", plan=plan, group=group,
                                 paths=[target])
    measures = await session.call("pipeline.measures", plan=corrected)

    rejected = next(m for m in measures["groups"][group] if m["frame"] == target)
    assert (rejected["approved"], rejected["rejected_by"], rejected["weight"]) == (
        False, "manual", 0.0)
    summary = next(b for b in measures["summary"] if b["key"] == group)
    assert summary["rejected"] == 1
    assert summary["frames"] == summary["measured"] - 1


async def test_the_rejection_echoes_its_python_equivalent(session, raws, tmp_path):
    """Parity: the selector's gesture is written to the console, executable and copyable."""
    plan = await _full_run(session, raws, str(tmp_path / "out"))
    group = "light_L_5s_bin1_g120_m10C"
    target = (await session.call("pipeline.measures", plan=plan))["groups"][group][0]["frame"]
    session.clear()

    await session.call("pipeline.set_rejects", plan=plan, group=group, paths=[target])
    await session.drain()

    codes = [p["code"] for p in session.of("echo")]
    assert any(f"retina.pipeline.set_rejects(plan, {group!r}, [{target!r}])" in c
               for c in codes)


async def test_the_rejection_travels_in_the_returned_plan(session, raws, tmp_path):
    """The state lives on the client: the corrected plan must carry the rejection, ready to
    relaunch."""
    plan = await _full_run(session, raws, str(tmp_path / "out"))
    group = "light_L_5s_bin1_g120_m10C"
    target = (await session.call("pipeline.measures", plan=plan))["groups"][group][0]["frame"]

    corrected = await session.call("pipeline.set_rejects", plan=plan, group=group,
                                 paths=[target])

    step_id = next(s for s in corrected["steps"] if s["id"] == f"measure_{group}")
    assert step_id["processes"][0]["values"]["manual_rejects"] == [target]


async def test_rejecting_does_not_force_a_remeasure(session, raws, tmp_path):
    """The whole point: dropping one frame costs an integration, not a hundred measurements."""
    plan = await _full_run(session, raws, str(tmp_path / "out"))
    group = "light_L_5s_bin1_g120_m10C"
    target = (await session.call("pipeline.measures", plan=plan))["groups"][group][0]["frame"]
    corrected = await session.call("pipeline.set_rejects", plan=plan, group=group,
                                 paths=[target])

    await session.call("pipeline.run", plan=corrected)
    end = await _wait(session)

    report = end["result"]
    assert f"measure_{group}" in report["skipped"]
    assert f"integrate_{group}" in report["executed"]


async def test_an_unknown_group_returns_a_domain_error(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))

    with pytest.raises(RpcFailure) as exc:
        await session.call("pipeline.set_rejects", plan=plan, group="nonexistent", paths=[])

    assert exc.value.code == -32000


async def test_the_report_carries_the_real_total_integration_time(session, raws, tmp_path):
    """Watching the night melt away as frames are dropped: that is what justifies sorting."""
    await _full_run(session, raws, str(tmp_path / "out"))
    group = "light_L_5s_bin1_g120_m10C"

    report = await session.call("pipeline.report")

    summary = next(b for b in report["products"] if b["key"] == group)
    assert summary["integration"] == pytest.approx(summary["frames"] * summary["exposure"])


# --- plan editing -------------------------------------------------------------------------
#
# The plan travels both ways, just as for the selection: the server keeps nothing, the client
# hands the corrected plan back to `run`. What matters here is that a refusal is a readable
# **domain error**, and not a silently wrong plan relaunched for three hours.

def _calibration_step(plan: dict) -> tuple[str, int]:
    for step in plan["steps"]:
        for index, process in enumerate(step["processes"]):
            if process["process_id"] == "ImageCalibration":
                return step["id"], index
    raise AssertionError("the test dataset must produce a calibration")


async def test_a_step_parameter_is_set_and_comes_back_in_the_plan(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    step_id, index = _calibration_step(plan)

    corrected = await session.call("pipeline.set_step_params", plan=plan, step_id=step_id,
                                 index=index, values={"pedestal_mode": "none"})

    step = next(s for s in corrected["steps"] if s["id"] == step_id)
    assert step["processes"][index]["values"]["pedestal_mode"] == "none"


async def test_the_edit_echoes_its_python_equivalent(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    step_id, index = _calibration_step(plan)
    session.clear()

    await session.call("pipeline.set_step_params", plan=plan, step_id=step_id, index=index,
                       values={"pedestal_mode": "none"})
    await session.drain()

    codes = [p["code"] for p in session.of("echo")]
    assert any("retina.pipeline.set_step_params(plan, " in c for c in codes)


async def test_an_invalid_value_returns_a_domain_error(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    step_id, index = _calibration_step(plan)

    with pytest.raises(RpcFailure) as exc:
        await session.call("pipeline.set_step_params", plan=plan, step_id=step_id,
                           index=index, values={"pedestal_mode": "wild_guess"})

    assert exc.value.code == -32000


async def test_a_hook_is_set_and_removed(session, raws, tmp_path):
    script = tmp_path / "after.py"
    script.write_text("pass\n", encoding="utf-8")
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    step_id = plan["steps"][0]["id"]

    frame = await session.call("pipeline.set_hooks", plan=plan, step_id=step_id,
                              after=str(script))
    assert next(s for s in frame["steps"] if s["id"] == step_id)["hooks"] == {
        "after": str(script)}

    removed = await session.call("pipeline.set_hooks", plan=frame, step_id=step_id, after=None)
    assert "hooks" not in next(s for s in removed["steps"] if s["id"] == step_id)


async def test_a_missing_hook_returns_a_domain_error(session, raws, tmp_path):
    inventory = await session.call("pipeline.scan", path=raws)
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))

    with pytest.raises(RpcFailure) as exc:
        await session.call("pipeline.set_hooks", plan=plan,
                           step_id=plan["steps"][0]["id"], before="/does/not/exist.py")

    assert exc.value.code == -32000
