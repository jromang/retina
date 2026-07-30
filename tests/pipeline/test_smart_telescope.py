"""Smart telescope ingestion: presets, dual-band, framing-mode mosaic.

Three capabilities that only make sense together, because they describe the same device: a
Seestar or a Dwarf produces hundreds of short exposures, on an **unregulated** color sensor,
sometimes behind a dual-band filter, and sometimes sweeping across several pointings.

What these tests protect are the three ways the generic pipeline used to get this data wrong:
it split the darks by temperature (one group per exposure), it debayered a dual-band frame
(mixing Ha and OIII in every pixel, irrecoverably), and it threw all the panels of a mosaic
into a single group, where registration stood no chance.
"""

from __future__ import annotations

import os

import pytest
from retina.pipeline import plan, scan
from retina.pipeline.presets import PRESETS, resolve
from retina.pipeline.synthetic import make_dataset

# --- presets ------------------------------------------------------------------------

def test_the_smart_telescope_presets_exist():
    assert {"seestar", "dwarf"} <= set(PRESETS)


def test_the_seestar_preset_widens_the_temperature_tolerance():
    """The sensor is not regulated: splitting by temperature would give a group per exposure."""
    settings = resolve("seestar")

    assert settings.tolerances()["temperature_tol"] >= 50.0
    assert settings.debayer is True


def test_a_preset_without_tolerances_imposes_none():
    """`None` must leave the module constants in place, not replace them with zero."""
    assert resolve("auto").tolerances() == {}


def test_the_preset_labels_come_from_the_catalog():
    """Hard-coded, they used to show up in French inside the English interface."""
    from retina.pipeline import describe_presets

    labels = {p["name"]: p["label"] for p in describe_presets()}
    assert labels["auto"] == "Automatic"  # the suite pins English (conftest)
    assert labels["seestar"]


# --- dual-band ----------------------------------------------------------------------

@pytest.fixture
def plan_dual_band(raws_osc, tmp_path):
    settings = resolve("osc")
    settings.dual_band = True
    return plan(scan(raws_osc), settings, output_dir=str(tmp_path / "out"))


def test_dual_band_produces_two_labeled_integrations(plan_dual_band):
    products = {p.filter: p for p in plan_dual_band.products}

    assert set(products) == {"Ha", "OIII"}


def test_dual_band_extracts_both_bands(plan_dual_band):
    extractions = [s for s in plan_dual_band.steps if s.id.startswith("extract_")]

    bands = {p.band for s in extractions for p in s.processes
              if p.process_id == "ExtractDualBand"}
    assert bands == {"ha", "oiii"}


def test_dual_band_does_not_debayer(plan_dual_band):
    """Interpolating would mix Ha (red) and OIII (green): the lines would no longer be
    separable, and nothing in the final image would say so."""
    assert not any(p.process_id == "Debayer"
                   for s in plan_dual_band.steps for p in s.processes)


def test_dual_band_says_so_in_the_notes(plan_dual_band):
    assert any("dual-band" in note for note in plan_dual_band.notes)


def test_without_dual_band_the_plan_is_unchanged(raws_osc, tmp_path):
    """Non-regression: the flag defaults to `False` and must cost nothing."""
    ordinary = plan(scan(raws_osc), "osc", output_dir=str(tmp_path / "a"))

    assert any(p.process_id == "Debayer" for s in ordinary.steps for p in s.processes)
    assert not any(s.id.startswith("extract_") for s in ordinary.steps)


# --- mosaic -------------------------------------------------------------------------

@pytest.fixture
def plan_framing(raws_framing, tmp_path):
    return plan(scan(raws_framing), "auto", output_dir=str(tmp_path / "out"))


def test_each_panel_is_integrated_separately(plan_framing):
    integrations = [s.id for s in plan_framing.steps if s.id.startswith("integrate_")]

    assert len(integrations) == 2
    assert all("panel" in s for s in integrations)


def test_the_mosaic_is_assembled_at_the_end_of_the_plan(plan_framing):
    mosaic = [s for s in plan_framing.steps if s.id.startswith("mosaic")]

    assert len(mosaic) == 1
    (step,) = mosaic
    assert step.processes[0].process_id == "MosaicReproject"
    assert len(step.inputs) == 2, "both panels must feed the assembly"
    assert step is plan_framing.steps[-1], "the mosaic is the last hand laid on the image"


def test_astrometry_is_switched_on_by_default_for_a_mosaic(plan_framing):
    """Without WCS, the panels cannot be placed relative to one another.
    Plate-solving stays disabled everywhere else (it downloads its indexes)."""
    solves = [s for s in plan_framing.steps if s.id.startswith("platesolve_")]

    assert len(solves) == 2
    assert any("astrometry enabled" in note for note in plan_framing.notes)


def test_the_mosaic_says_so_in_the_notes(plan_framing):
    assert any("mosaic panels" in note for note in plan_framing.notes)


def test_a_single_pointing_does_not_trigger_a_mosaic(raws_mono, tmp_path):
    """The common case: nothing must change, and above all plate-solving must not switch on."""
    ordinary = plan(scan(raws_mono), "auto", output_dir=str(tmp_path / "out"))

    assert not any(s.id.startswith("mosaic") for s in ordinary.steps)
    assert not any(s.id.startswith("platesolve_") for s in ordinary.steps)


def test_the_mosaic_survives_serialization(plan_framing):
    from retina.pipeline.plan import Plan

    reread = Plan.from_dict(plan_framing.to_dict())

    (step,) = [s for s in reread.steps if s.id.startswith("mosaic")]
    assert step.processes[0].process_id == "MosaicReproject"


# --- registration reference ---------------------------------------------------------

def test_each_panel_has_its_own_reference(raws_framing, tmp_path):
    """The subtlest point here. A single shared reference exists so that the L/R/G/B layers
    line up; between disjoint panels it would ask us to match stars that have no reason to be
    the same ones."""
    from retina.pipeline import run

    p = plan(scan(raws_framing), "auto", output_dir=str(tmp_path / "out"))
    # Plate-solving downloads its indexes: switch it off, the mosaic is not the subject here.
    p.steps = [s for s in p.steps if not s.id.startswith(("platesolve_", "mosaic"))]

    report = run(p)

    references = [n for n in report.notes if "registration reference" in n]
    assert len(references) >= 2, "one reference per panel must be announced"
    files = {n.split()[-3] for n in report.notes if n.startswith("panel ")}
    assert len(files) == 2, "the two panels cannot share a single reference"


def test_without_a_mosaic_the_reference_stays_unique(raws_mono, tmp_path):
    """The rule holds everywhere else: a single reference for the whole batch."""
    from retina.pipeline import run

    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path / "out"))
    report = run(p)

    assert report.reference
    assert not any(n.startswith("panel ") for n in report.notes)


def test_scanning_a_seestar_folder_groups_without_splitting(tmp_path):
    """The preset end to end: darks at scattered temperatures stay a single group."""
    root = tmp_path / "seestar"
    root.mkdir()
    make_dataset(str(root), "osc")
    inventory = scan(str(root))

    batches = inventory.groups(**resolve("seestar").tolerances())

    darks = [g for g in batches if g.kind == "dark"]
    assert len(darks) == 1, f"the darks split apart: {[g.key for g in darks]}"
    assert os.path.isdir(str(root))
