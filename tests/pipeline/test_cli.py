"""The CLI: the whole pipeline with no shell — the test of the "headless first" rule."""

from __future__ import annotations

import os

import pytest
from retina.pipeline.__main__ import main


def test_plan_only_prints_the_plan_without_writing_anything(raws_mono, tmp_path, capsys):
    code = main([raws_mono, "--out", str(tmp_path / "out"), "--plan-only"])
    output = capsys.readouterr().out

    assert code == 0
    assert "20 frames" in output
    assert "steps" in output
    assert not os.path.exists(tmp_path / "out")


def test_a_full_run_produces_the_integrated_frames(raws_mono, tmp_path, capsys):
    code = main([raws_mono, "--out", str(tmp_path / "out")])
    output = capsys.readouterr().out

    assert code == 0
    assert "step(s) executed" in output
    integrated = sorted(os.listdir(tmp_path / "out" / "integrated"))
    assert [f for f in integrated if f.endswith("_crop.fits")] == [
        "light_L_5s_bin1_g120_m10C_crop.fits", "light_R_5s_bin1_g120_m10C_crop.fits"]


def test_the_preset_is_taken_into_account(raws_mono, tmp_path, capsys):
    main([raws_mono, "--out", str(tmp_path / "out"), "--preset", "mono_sho",
          "--plan-only"])

    assert "Ha, SII, OIII" in capsys.readouterr().out


def test_the_plan_can_be_written_then_read_back(raws_mono, tmp_path, capsys):
    from retina.pipeline.plan import Plan

    path = str(tmp_path / "plan.json")
    main([raws_mono, "--out", str(tmp_path / "out"), "--plan-only",
          "--save-plan", path])

    assert "Plan written" in capsys.readouterr().out
    assert len(Plan.load(path).steps) == 18


def test_an_empty_folder_returns_an_error_code(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    code = main([str(tmp_path / "empty")])

    assert code == 1
    assert "No frame" in capsys.readouterr().err


def test_a_missing_folder_raises():
    with pytest.raises(ValueError, match="not found"):
        main(["/path/that/does/not/exist"])


def test_an_unknown_preset_is_rejected_by_the_argument_parser(raws_mono):
    with pytest.raises(SystemExit):
        main([raws_mono, "--preset", "mono_hoo"])
