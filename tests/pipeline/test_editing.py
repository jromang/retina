"""Editing a built plan: tuning a step, hanging scripts off it.

What is checked here is not that a value gets written — it is that a **wrong** value never
gets in. A `sigma=-4` accepted at click time only fails three hours of computation later,
inside a thread, with a message that does not say where it came from. The refusal must
therefore be immediate, and must leave the plan exactly as it was.
"""

from __future__ import annotations

import os

import pytest
from retina.pipeline import cache, plan, scan, set_hooks, set_step_params
from retina.pipeline.plan import Plan


@pytest.fixture(scope="module")
def built(raws_mono, tmp_path_factory) -> Plan:
    return plan(scan(raws_mono), "auto",
                output_dir=str(tmp_path_factory.mktemp("editing")))


def _calibration_step(p: Plan):
    """The first step carrying an ImageCalibration — the one you tune in practice."""
    for step in p.steps:
        for index, process in enumerate(step.processes):
            if process.process_id == "ImageCalibration":
                return step, index
    pytest.skip("the test dataset produces no calibration")


# --- tuning a parameter -------------------------------------------------------------

def test_a_value_that_is_set_survives_serialization(built):
    """The edit → JSON → run loop is what makes the plan replayable."""
    step, index = _calibration_step(built)
    set_step_params(built, step.id, index, {"pedestal_mode": "none"})

    reread = Plan.from_dict(built.to_dict())
    assert reread.step(step.id).processes[index].pedestal_mode == "none"


def test_the_other_parameters_do_not_move(built):
    """This is a partial update: tuning the pedestal does not reset the masters."""
    step, index = _calibration_step(built)
    before = step.processes[index].values()

    set_step_params(built, step.id, index, {"pedestal": 0.002})

    after = built.step(step.id).processes[index].values()
    assert after["pedestal"] == pytest.approx(0.002)
    assert {k: v for k, v in after.items() if k != "pedestal"} == \
           {k: v for k, v in before.items() if k != "pedestal"}


def test_an_unknown_parameter_is_rejected(built):
    step, index = _calibration_step(built)
    with pytest.raises(ValueError, match="unknown parameters"):
        set_step_params(built, step.id, index, {"does_not_exist": 1})


def test_a_choice_outside_the_enumeration_is_rejected(built):
    """``coerce`` does not look at ``choices`` — without this guard, the value went through."""
    step, index = _calibration_step(built)
    with pytest.raises(ValueError, match="is not one of"):
        set_step_params(built, step.id, index, {"pedestal_mode": "guesswork"})


def test_an_out_of_range_value_is_rejected(built):
    step, index = _calibration_step(built)
    with pytest.raises(ValueError, match="below the minimum"):
        set_step_params(built, step.id, index, {"pedestal": -5.0})


def test_a_refusal_leaves_the_step_intact(built):
    """The plan is rebuilt then validated: a refusal must not have written anything on the way."""
    step, index = _calibration_step(built)
    before = step.processes[index].values()
    with pytest.raises(ValueError):
        set_step_params(built, step.id, index, {"pedestal_mode": "guesswork"})
    assert built.step(step.id).processes[index].values() == before


def test_a_bound_parameter_is_rejected(built):
    """``@reference`` and ``@weights`` are resolved by the runner: setting them would be a lie."""
    bound = [s for s in built.steps if s.bindings]
    if not bound:
        pytest.skip("no late binding in this plan")
    step = bound[0]
    name = next(iter(step.bindings))
    with pytest.raises(ValueError, match="resolved at run time"):
        set_step_params(built, step.id, 0, {name: "/data/whatever.fits"})


def test_an_unknown_step_is_rejected(built):
    with pytest.raises(KeyError, match="Unknown step"):
        set_step_params(built, "step_that_does_not_exist", 0, {})


def test_an_index_outside_the_recipe_is_rejected(built):
    step, _ = _calibration_step(built)
    with pytest.raises(IndexError, match="no index"):
        set_step_params(built, step.id, 99, {})


# --- Python hooks -------------------------------------------------------------------

def test_a_hook_travels_inside_the_plan(built, tmp_path):
    script = tmp_path / "after.py"
    script.write_text("pass\n", encoding="utf-8")
    step = built.steps[0]

    set_hooks(built, step.id, after=str(script))

    reread = Plan.from_dict(built.to_dict())
    assert reread.step(step.id).hooks == {"after": str(script)}
    set_hooks(built, step.id, after=None)


def test_a_plan_without_hooks_does_not_serialize_the_key(built):
    """A plan saved before hooks existed must read back unchanged."""
    step = built.steps[0]
    assert not step.hooks
    assert "hooks" not in step.to_dict()


def test_a_missing_script_is_rejected(built):
    with pytest.raises(FileNotFoundError, match="Hook script not found"):
        set_hooks(built, built.steps[0].id, before="/does/not/exist.py")


def test_the_hook_contents_enter_the_fingerprint(built, tmp_path):
    """Editing the script must replay the step: otherwise its new version would seem applied."""
    script = tmp_path / "hook.py"
    script.write_text("x = 1\n", encoding="utf-8")
    step = built.steps[0]

    bare = cache.fingerprint(step)
    set_hooks(built, step.id, after=str(script))
    hooked = cache.fingerprint(step)
    script.write_text("x = 2\n", encoding="utf-8")
    edited = cache.fingerprint(step)

    assert bare != hooked, "setting a hook must change the fingerprint"
    assert hooked != edited, "editing the script must change the fingerprint"
    set_hooks(built, step.id, after=None)
    assert cache.fingerprint(step) == bare, "removing it must restore the original fingerprint"


def test_the_hook_runs_and_sees_its_context(raws_mono, tmp_path_factory, tmp_path):
    """The step context arrives through ``retina.parameters`` — that is what makes it useful."""
    from retina.pipeline import run

    control = tmp_path / "witness.txt"
    script = tmp_path / "hook.py"
    script.write_text(
        "import json, retina\n"
        "params = {name: retina.parameters.get(name) for name in\n"
        "          ('step_id', 'phase', 'group', 'inputs', 'outputs')}\n"
        f"open({str(control)!r}, 'w').write(json.dumps(params))\n",
        encoding="utf-8",
    )
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path_factory.mktemp("hook_run")))
    target = p.steps[0]
    set_hooks(p, target.id, before=str(script))

    run(p)

    assert control.exists(), "the hook did not run"
    import json

    context = json.loads(control.read_text(encoding="utf-8"))
    assert context["step_id"] == target.id
    assert context["phase"] == "before"
    assert context["inputs"] == list(target.inputs)


def test_a_step_served_from_the_cache_does_not_replay_the_hook(raws_mono, tmp_path_factory,
                                                               tmp_path):
    """The hook is in the fingerprint: replaying it would run it twice per output."""
    from retina.pipeline import run

    counter = tmp_path / "calls.txt"
    script = tmp_path / "count.py"
    script.write_text(
        f"open({str(counter)!r}, 'a').write('x')\n", encoding="utf-8")
    output = str(tmp_path_factory.mktemp("hook_cache"))
    p = plan(scan(raws_mono), "auto", output_dir=output)
    # A step with an output, otherwise the cache has nothing to seal.
    target = next(s for s in p.steps if s.outputs)
    set_hooks(p, target.id, after=str(script))

    run(p)
    first = counter.read_text(encoding="utf-8") if counter.exists() else ""
    report = run(p)

    assert target.id in report.skipped, "the step should have been served from the cache"
    after = counter.read_text(encoding="utf-8") if counter.exists() else ""
    assert after == first, "the hook was replayed on a cached step"


# --- output pedestal ----------------------------------------------------------------

def test_the_presets_pedestal_reaches_the_calibration(raws_mono, tmp_path_factory):
    from retina.pipeline.presets import resolve

    settings = resolve("auto")
    settings.pedestal_mode = "manual"
    settings.pedestal = 0.01
    p = plan(scan(raws_mono), settings,
             output_dir=str(tmp_path_factory.mktemp("pedestal")))

    calibrations = [proc for s in p.steps for proc in s.processes
                    if proc.process_id == "ImageCalibration"]
    assert calibrations, "the test dataset must produce a calibration"
    # The lights carry the pedestal; flats and darks stay at `none` — they are positive by
    # construction.
    lights = [proc for s in p.steps if (s.group or "").startswith("light")
              for proc in s.processes if proc.process_id == "ImageCalibration"]
    assert lights, "no light calibration"
    assert all(proc.pedestal_mode == "manual" for proc in lights)
    assert all(proc.pedestal == pytest.approx(0.01) for proc in lights)


def test_the_presets_tolerances_are_passed_to_the_grouping(raws_mono, tmp_path_factory,
                                                           monkeypatch):
    """Without this wiring, a preset could advertise a tolerance that nobody applied."""
    from retina.pipeline import scan as scan_mod  # noqa: F401  (the function, not the module)
    from retina.pipeline.scan import Inventory

    views = {}
    original = Inventory.groups

    def spy(self, **tolerances):
        views.update(tolerances)
        return original(self, **tolerances)

    monkeypatch.setattr(Inventory, "groups", spy)
    plan(scan(raws_mono), "seestar",
         output_dir=str(tmp_path_factory.mktemp("tolerances")))

    assert views == {"temperature_tol": 100.0}


def test_the_hook_path_is_expanded(built, tmp_path, monkeypatch):
    """``~/scripts/x.py`` is what the user types; the plan must store the absolute path."""
    # `expanduser` does not read the same variable everywhere: POSIX looks at $HOME, Windows
    # at $USERPROFILE (then $HOMEDRIVE+$HOMEPATH). Setting both makes the test true on either
    # side — otherwise it expanded "~" to the user's real profile, and failed.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    script = tmp_path / "home.py"
    script.write_text("pass\n", encoding="utf-8")
    step = built.steps[0]

    set_hooks(built, step.id, before=os.path.join("~", "home.py"))

    assert built.step(step.id).hooks["before"] == str(script)
    set_hooks(built, step.id, before=None)
