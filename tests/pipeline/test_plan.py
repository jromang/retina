"""The execution plan: contents, phase ordering, serialization."""

from __future__ import annotations

import json
import os

import pytest
from retina.pipeline import scan
from retina.pipeline.plan import REFERENCE, WEIGHTS, Plan, plan
from retina.pipeline.presets import PRESETS, Preset, describe_presets, resolve
from retina.process.container import ProcessContainer


def ids(p: Plan) -> list[str]:
    return [s.id for s in p.steps]


def processes_of(p: Plan, step_id: str) -> list[str]:
    return [x.process_id for x in p.step(step_id).processes]


# --- plan contents -------------------------------------------------------------------

def test_the_mono_plan_chains_the_expected_steps(raws_mono):
    p = plan(scan(raws_mono), "auto")

    assert ids(p) == [
        "master_bias_bin1_g120_m10C",
        "master_dark_5s_bin1_g120_m10C",
        "calibrate_flat_L_bin1_g120_m10C", "master_flat_L_bin1_g120_m10C",
        "calibrate_flat_R_bin1_g120_m10C", "master_flat_R_bin1_g120_m10C",
        "calibrate_light_L_5s_bin1_g120_m10C", "calibrate_light_R_5s_bin1_g120_m10C",
        "measure_light_L_5s_bin1_g120_m10C", "measure_light_R_5s_bin1_g120_m10C",
        "register_light_L_5s_bin1_g120_m10C", "register_light_R_5s_bin1_g120_m10C",
        "normalize_light_L_5s_bin1_g120_m10C", "normalize_light_R_5s_bin1_g120_m10C",
        "integrate_light_L_5s_bin1_g120_m10C", "integrate_light_R_5s_bin1_g120_m10C",
        "autocrop_light_L_5s_bin1_g120_m10C", "autocrop_light_R_5s_bin1_g120_m10C",
    ]


def test_every_measurement_comes_before_the_first_registration(raws_mono):
    """The reference must be shared by every filter: otherwise L and R will not line up."""
    names = ids(plan(scan(raws_mono), "auto"))
    last_measurement = max(i for i, n in enumerate(names) if n.startswith("measure_"))
    first_registration = min(i for i, n in enumerate(names) if n.startswith("register_"))

    assert last_measurement < first_registration


def test_light_calibration_chains_the_full_recipe(raws_mono):
    p = plan(scan(raws_mono), "auto")

    assert processes_of(p, "calibrate_light_L_5s_bin1_g120_m10C") == [
        "ImageCalibration", "CosmeticCorrection"]


def test_the_masters_are_wired_into_the_calibration(raws_mono):
    p = plan(scan(raws_mono), "auto")
    calibration = p.step("calibrate_light_L_5s_bin1_g120_m10C").processes[0]

    assert calibration.master_dark.endswith("master_dark_5s_bin1_g120_m10C.fits")
    assert calibration.master_flat.endswith("master_flat_L_bin1_g120_m10C.fits")
    assert calibration.master_bias == ""      # the exact dark already carries the bias
    assert calibration.dark_scale == 1.0
    assert calibration.pedestal_mode == "auto"


def test_the_flat_is_calibrated_by_the_bias(raws_mono):
    p = plan(scan(raws_mono), "auto")
    calibration = p.step("calibrate_flat_L_bin1_g120_m10C").processes[0]

    assert calibration.master_bias.endswith("master_bias_bin1_g120_m10C.fits")
    assert calibration.master_dark == ""      # no 1 s flat-dark in this dataset
    assert calibration.pedestal_mode == "none"  # a flat is always positive


def test_osc_adds_the_debayering(raws_osc):
    p = plan(scan(raws_osc), "auto")
    step = next(s for s in p.steps if s.id.startswith("calibrate_light"))

    assert [x.process_id for x in step.processes][-1] == "Debayer"
    assert step.processes[-1].pattern == "RGGB"


def test_a_preset_can_force_or_forbid_the_debayering(raws_osc):
    force = plan(scan(raws_osc), "mono_lrgb")
    step = next(s for s in force.steps if s.id.startswith("calibrate_light"))

    assert "Debayer" not in [x.process_id for x in step.processes]


def test_the_late_bindings_are_declared(raws_mono):
    p = plan(scan(raws_mono), "auto")

    assert p.step("register_light_L_5s_bin1_g120_m10C").bindings == {"reference_path": REFERENCE}
    assert p.step("integrate_light_L_5s_bin1_g120_m10C").bindings == {"weights": WEIGHTS}


def test_the_output_paths_are_deterministic(raws_mono):
    """A necessary condition for the cache and for resuming after an interruption."""
    a = plan(scan(raws_mono), "auto")
    b = plan(scan(raws_mono), "auto")

    assert [s.outputs for s in a.steps] == [s.outputs for s in b.steps]
    assert all(os.path.isabs(o) for s in a.steps for o in s.outputs)


def test_the_announced_results_are_the_cropped_images(raws_mono):
    """Cropping is the last hand laid on the image: it is the result."""
    p = plan(scan(raws_mono), "auto")

    assert sorted(os.path.basename(r) for r in p.results) == [
        "light_L_5s_bin1_g120_m10C_crop.fits", "light_R_5s_bin1_g120_m10C_crop.fits"]


def test_without_cropping_the_result_stays_the_integrated_image(raws_mono):
    p = plan(scan(raws_mono), Preset(name="raw", autocrop=False))

    assert sorted(os.path.basename(r) for r in p.results) == [
        "light_L_5s_bin1_g120_m10C.fits", "light_R_5s_bin1_g120_m10C.fits"]


def test_the_output_folder_is_configurable(raws_mono, tmp_path):
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path / "elsewhere"))

    assert p.output_dir == str(tmp_path / "elsewhere")
    assert all(o.startswith(p.output_dir) for s in p.steps for o in s.outputs)


# --- preset options ------------------------------------------------------------------

def test_without_registration_or_measurement_the_plan_shrinks(raws_mono):
    settings = Preset(name="raw", measure=False, register=False, cosmetic=False)
    p = plan(scan(raws_mono), settings)

    assert not [n for n in ids(p) if n.startswith(("measure_", "register_"))]
    assert p.step("integrate_light_L_5s_bin1_g120_m10C").bindings == {}


def test_the_superbias_replaces_the_master_bias(raws_mono):
    p = plan(scan(raws_mono), Preset(name="sb", superbias=True))
    calibration = p.step("calibrate_flat_L_bin1_g120_m10C").processes[0]

    assert "superbias_bias_bin1_g120_m10C" in ids(p)
    assert calibration.master_bias.endswith("_superbias.fits")


def test_the_preset_thresholds_reach_the_integration(raws_mono):
    p = plan(scan(raws_mono), Preset(name="hard", sigma_low=2.0, sigma_high=1.5))
    integration = p.step("integrate_light_L_5s_bin1_g120_m10C").process

    assert (integration.sigma_low, integration.sigma_high) == (2.0, 1.5)


def test_an_expected_but_missing_filter_is_reported(raws_mono):
    p = plan(scan(raws_mono), "mono_lrgb")

    assert any("G, B" in n for n in p.notes)


def test_the_matching_notes_surface_in_the_plan(raws_mono):
    """A dark with a distant exposure must show in the plan, not only in the log."""
    inventory = scan(raws_mono)
    groups = inventory.groups()
    # push the dark away: 5 s → 300 s, without touching the files
    next(g for g in groups if g.kind == "dark").exposure = 300.0
    p = plan(inventory, "auto", groups=groups)

    assert any("too far from" in n for n in p.notes)
    # with the dark ruled out, calibration falls back on the bias alone
    calibration = p.step("calibrate_light_L_5s_bin1_g120_m10C").processes[0]
    assert calibration.master_dark == ""
    assert calibration.master_bias.endswith("master_bias_bin1_g120_m10C.fits")


def test_the_dark_current_step_is_planned_when_scaling_is_required():
    """Scaling ⇒ one more step: master dark − master bias."""
    from retina.pipeline.groups import FrameGroup
    from retina.pipeline.scan import FrameInfo, Inventory

    def frames(kind, n, expo, filter=None):
        return [FrameInfo(path=f"/data/{kind}{i}.fits", kind=kind, exposure=expo,
                          filter=filter, width=64, height=64) for i in range(n)]

    groups = [
        FrameGroup(kind="bias", exposure=0.0, width=64, height=64,
                   frames=frames("bias", 3, 0.0)),
        FrameGroup(kind="dark", exposure=300.0, width=64, height=64,
                   frames=frames("dark", 3, 300.0)),
        FrameGroup(kind="light", filter="L", exposure=150.0, width=64, height=64,
                   frames=frames("light", 4, 150.0, "L")),
    ]
    p = plan(Inventory(root="/data", frames=[f for g in groups for f in g.frames]),
             "auto", groups=groups)

    current = next(s for s in p.steps if s.id.startswith("darkcurrent_"))
    assert current.processes[0].master_bias.endswith("master_bias_bin1_xC.fits")
    assert current.inputs == [current.processes[0].master_bias.replace(
        "master_bias_bin1_xC", "master_dark_300s_bin1_xC")]

    calibration = p.step("calibrate_light_L_150s_bin1_xC").processes[0]
    assert calibration.master_dark.endswith("_current.fits")
    assert calibration.master_bias.endswith("master_bias_bin1_xC.fits")
    assert calibration.dark_scale == 0.5


# --- inspection, editing, serialization ----------------------------------------------

def test_a_step_exports_as_an_ordinary_recipe(raws_mono):
    p = plan(scan(raws_mono), "auto")
    recipe = p.container_for("calibrate_light_L_5s_bin1_g120_m10C")

    assert isinstance(recipe, ProcessContainer)
    assert len(recipe) == 2
    # it goes back through the recipe XML: nothing new was invented
    assert ProcessContainer.from_xml(recipe.to_xml()).processes[0].process_id \
        == "ImageCalibration"


def test_a_parameter_can_be_edited_and_survives_serialization(raws_mono):
    p = plan(scan(raws_mono), "auto")
    p.step("integrate_light_L_5s_bin1_g120_m10C").process.sigma_high = 2.5

    reread = Plan.from_dict(json.loads(json.dumps(p.to_dict())))

    assert reread.step("integrate_light_L_5s_bin1_g120_m10C").process.sigma_high == 2.5


def test_the_plan_makes_a_full_json_round_trip(raws_mono):
    p = plan(scan(raws_mono), "mono_lrgb")
    reread = Plan.from_dict(json.loads(json.dumps(p.to_dict())))

    assert ids(reread) == ids(p)
    assert reread.notes == p.notes
    assert reread.preset.name == "mono_lrgb"
    assert reread.output_dir == p.output_dir
    assert [s.outputs for s in reread.steps] == [s.outputs for s in p.steps]
    assert [s.bindings for s in reread.steps] == [s.bindings for s in p.steps]
    assert processes_of(reread, "calibrate_light_L_5s_bin1_g120_m10C") \
        == processes_of(p, "calibrate_light_L_5s_bin1_g120_m10C")


def test_the_plan_saves_and_reloads(raws_mono, tmp_path):
    p = plan(scan(raws_mono), "auto")
    path = str(tmp_path / "plan.json")
    p.save(path)

    assert ids(Plan.load(path)) == ids(p)


def test_a_plan_of_an_incompatible_version_is_rejected(raws_mono):
    data = plan(scan(raws_mono), "auto").to_dict()
    data["version"] = "99.0"

    with pytest.raises(ValueError, match="version"):
        Plan.from_dict(data)


def test_the_plan_describes_what_it_is_going_to_do(raws_mono):
    text = plan(scan(raws_mono), "auto").describe()

    assert "18 steps" in text
    assert "Integration" in text
    assert "light_L_5s_bin1_g120_m10C_crop.fits" in text


def test_the_python_echo_of_the_plan_is_executable(raws_mono):
    source = plan(scan(raws_mono), "osc").to_python_source()

    assert "retina.pipeline.scan(" in source
    assert "preset='osc'" in source
    compile(source, "<echo>", "exec")


def test_an_unknown_step_raises(raws_mono):
    with pytest.raises(KeyError):
        plan(scan(raws_mono), "auto").step("does_not_exist")


# --- presets --------------------------------------------------------------------------

def test_presets_resolve_from_a_name_an_object_or_a_dict():
    assert resolve("osc").debayer is True
    assert resolve(None).name == "auto"
    assert resolve(Preset(name="x", cosmetic=False)).cosmetic is False
    assert resolve({"name": "y", "sigma_low": 2.0}).sigma_low == 2.0


def test_resolving_a_named_preset_returns_a_copy():
    """A caller who tweaks a preset must not contaminate the next ones."""
    copy = resolve("osc")
    copy.cosmetic = False

    assert PRESETS["osc"].cosmetic is True


def test_an_unknown_preset_raises():
    with pytest.raises(ValueError, match="Unknown preset"):
        resolve("mono_hoo")


def test_presets_are_serializable():
    for name, settings in PRESETS.items():
        assert Preset.from_dict(json.loads(json.dumps(settings.to_dict()))) == settings, name


def test_presets_are_describable_for_the_ui():
    described = describe_presets()

    assert {d["name"] for d in described} == set(PRESETS)
    assert all(d["label"] and d["hint"] for d in described)


# --- what the plan promises, and what it costs -----------------------------------------
#
# Two numbers you want to read BEFORE launching three hours of computation: the total
# integration time of each final image, and the room it will need on disk.

def test_the_plan_describes_every_final_image(raws_mono, tmp_path):
    p = plan(scan(raws_mono), "mono_lrgb", output_dir=str(tmp_path / "out"))

    filters = {product.filter for product in p.products}
    assert filters == {"L", "R"}
    assert all(product.path.endswith(".fits") for product in p.products)
    assert {product.path for product in p.products} == set(p.results)


def test_the_total_integration_is_the_product_of_the_exposures(raws_mono, tmp_path):
    p = plan(scan(raws_mono), "mono_lrgb", output_dir=str(tmp_path / "out"))
    product = p.products[0]

    assert product.integration == product.frames * product.exposure


def test_an_unknown_exposure_does_not_fabricate_a_duration():
    """Better to announce nothing than to announce zero: that is not the same information."""
    from retina.pipeline.plan import PlanProduct

    assert PlanProduct(key="x", frames=10, exposure=None).integration is None


def test_the_plan_announces_the_room_it_will_take(raws_mono, tmp_path):
    p = plan(scan(raws_mono), "mono_lrgb", output_dir=str(tmp_path / "out"))
    disk = p.disk_usage()

    assert disk["total_bytes"] > 0
    assert set(disk["stages"]) <= {"masters", "calibrated", "registered", "integrated",
                                     "overscan"}
    assert sum(disk["stages"].values()) == disk["total_bytes"]
    # free space is measured on the first existing parent: the folder itself does not exist
    assert disk["free_bytes"] is not None


def test_drizzle_multiplies_the_room_by_the_square_of_its_factor(raws_mono, tmp_path):
    """This is precisely the setting that overflows a disk without warning."""
    inventory = scan(raws_mono)
    simple = plan(inventory, "mono_lrgb", output_dir=str(tmp_path / "a"))
    drizzle = plan(inventory, {"name": "d", "drizzle": True, "drizzle_scale": 2.0},
                   output_dir=str(tmp_path / "b"))

    integrated = lambda p: p.disk_usage()["stages"]["integrated"]  # noqa: E731
    assert integrated(drizzle) == pytest.approx(4 * integrated(simple), rel=0.01)


def test_the_products_survive_serialization(raws_mono, tmp_path):
    p = plan(scan(raws_mono), "mono_lrgb", output_dir=str(tmp_path / "out"))
    reread = Plan.from_dict(p.to_dict())

    assert [x.key for x in reread.products] == [x.key for x in p.products]
    assert [x.integration for x in reread.products] == [x.integration for x in p.products]
    assert reread.steps[0].output_bytes == p.steps[0].output_bytes


def test_measurements_do_not_count_as_an_image(raws_mono, tmp_path):
    """They write a JSON file of a few kilobytes, not one more frame per group."""
    p = plan(scan(raws_mono), "mono_lrgb", output_dir=str(tmp_path / "out"))

    measure = next(s for s in p.steps if s.id.startswith("measure_"))
    assert measure.output_bytes == 0
    assert "measures" not in p.disk_usage()["stages"]


def test_the_crop_that_follows_a_drizzle_stays_enlarged(raws_mono, tmp_path):
    """The enlargement does not stop at the step that introduces it."""
    p = plan(scan(raws_mono),
             {"name": "d", "drizzle": True, "drizzle_scale": 2.0, "autocrop": True},
             output_dir=str(tmp_path / "out"))

    integrated = next(s for s in p.steps if s.id.startswith("integrate_"))
    cropped = next(s for s in p.steps if s.id.startswith("autocrop_"))
    assert cropped.output_bytes == integrated.output_bytes


def test_the_cli_announces_the_same_summary_as_the_wizard(raws_mono, tmp_path):
    """Console completeness: `--plan-only` must say what the GUI shows."""
    text = plan(scan(raws_mono), "mono_lrgb",
                 output_dir=str(tmp_path / "out")).describe()

    assert "expected results" in text
    # the plan is built before any measurement: this number cannot know which frames the
    # selector will reject, and it must say so rather than let anyone believe otherwise
    assert "at most, before selection" in text
    assert "= 20 s" in text           # 4 exposures of 5 s, summed
    assert "to write:" in text
    assert "free" in text


def test_the_plan_notes_follow_the_language(raws_mono, monkeypatch):
    """End to end: it is the **domain** that translates, not the interface.

    The plan is built twice, in two languages, from the same inventory. What is checked is
    not the quality of the translation but that the whole chain holds — English msgid in
    `plan.py`, compiled catalogue, effective language resolved.
    """
    from retina import i18n

    inventory = scan(raws_mono)
    groups = inventory.groups()
    next(g for g in groups if g.kind == "dark").exposure = 300.0

    monkeypatch.setenv(i18n.ENV_VAR, "fr")
    i18n.invalidate()
    fr = plan(inventory, "auto", groups=inventory.groups())
    next(g for g in groups if g.kind == "dark").exposure = 300.0

    monkeypatch.setenv(i18n.ENV_VAR, "en")
    i18n.invalidate()
    en = plan(inventory, "auto", groups=inventory.groups())

    assert any("Intégration —" in s.label for s in fr.steps)
    assert any("Integration —" in s.label for s in en.steps)
    # And translated labels change **neither** the identifiers **nor the cache
    # fingerprint**. That second point is the only one that costs dearly if it breaks:
    # `label` appears in the manifest so that it can be read, but it must stay out of the
    # fingerprint — otherwise switching language would replay three hours of work already done.
    from retina.pipeline.cache import fingerprint

    assert [s.id for s in fr.steps] == [s.id for s in en.steps]
    assert [s.outputs for s in fr.steps] == [s.outputs for s in en.steps]
    assert [fingerprint(s) for s in fr.steps] == [fingerprint(s) for s in en.steps]
