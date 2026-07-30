"""Preferences.

What is checked: that a setting is the **same object** seen from the console and from the
network (the parity rule), that it survives a restart, that it is validated rather than merely
accepted, and that it actually reaches its consumers — a setting that changes nothing would be
worse than no setting at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from retina.app import Application
from retina.preferences import DELEGATED, SCHEMA, Preferences


@pytest.fixture
def prefs(tmp_path):
    echoes: list[str] = []
    return Preferences(echo=echoes.append, path=tmp_path / "preferences.json"), echoes


# --- the schema -----------------------------------------------------------------------

def test_keys_are_prefixed_by_their_group():
    """A flat identifier would make `set('language', …)` ambiguous at the first collision."""
    for group in SCHEMA:
        for param in group.parameters:
            assert param.id.startswith(f"{group.id}.")


def test_every_parameter_has_a_label():
    for group in SCHEMA:
        assert group.label
        for param in group.parameters:
            assert param.label


# --- reading and writing --------------------------------------------------------------

def test_an_unset_preference_returns_its_default(prefs):
    preferences, _ = prefs

    assert preferences.get("folders.temp_dir") == ""
    assert preferences.get("performance.max_workers") == 4


def test_only_non_default_values_are_written(tmp_path):
    """Writing the whole schema would freeze the defaults of the day it was installed."""
    path = tmp_path / "preferences.json"
    preferences = Preferences(path=path)

    preferences.set("performance.max_workers", 8)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["values"] == {"performance.max_workers": 8}


def test_a_preference_survives_a_restart(tmp_path):
    path = tmp_path / "preferences.json"
    Preferences(path=path).set("folders.temp_dir", str(tmp_path))

    assert Preferences(path=path).get("folders.temp_dir") == str(tmp_path)


def test_an_unreadable_file_returns_the_defaults_and_does_not_raise(tmp_path):
    """Losing settings is harmless; refusing to start over them would be absurd."""
    path = tmp_path / "preferences.json"
    path.write_text("{this is not json", encoding="utf-8")

    assert Preferences(path=path).get("performance.max_workers") == 4


def test_reset_clears_one_key_then_all_of_them(prefs):
    preferences, _ = prefs
    preferences.set("performance.max_workers", 9)
    preferences.set("viewport.readout_probe_size", 7)

    preferences.reset("performance.max_workers")
    assert preferences.get("performance.max_workers") == 4
    assert preferences.get("viewport.readout_probe_size") == 7

    preferences.reset()
    assert preferences.get("viewport.readout_probe_size") == 1


# --- validation -------------------------------------------------------------------------

def test_an_out_of_range_value_is_clamped(prefs):
    preferences, _ = prefs

    assert preferences.set("performance.max_workers", 999) == 32
    assert preferences.set("performance.max_workers", -5) == 1


def test_an_unknown_choice_raises_rather_than_slipping_through(prefs):
    """What `Parameter.coerce` does not do, and what a setting must."""
    preferences, _ = prefs

    with pytest.raises(ValueError, match="outside the allowed values"):
        preferences.set("viewport.mask_display_mode", "pink")


def test_an_unknown_key_says_what_does_exist(prefs):
    preferences, _ = prefs

    with pytest.raises(KeyError, match="known"):
        preferences.get("does.not.exist")
    with pytest.raises(KeyError):
        preferences.set("does.not.exist", 1)


def test_a_folder_is_expanded(prefs, monkeypatch):
    preferences, _ = prefs
    monkeypatch.setenv("HOME", "/home/someone")

    assert preferences.set("folders.temp_dir", "~/scratch") == str(
        Path("~/scratch").expanduser())


# --- echo and parity --------------------------------------------------------------------

def test_every_gesture_emits_its_python_code(prefs):
    """This is how one learns the API by clicking, and how a setting is replayed."""
    preferences, echoes = prefs

    preferences.set("performance.max_workers", 8)
    preferences.reset("performance.max_workers")

    assert echoes == ["app.preferences.set('performance.max_workers', 8)",
                      "app.preferences.reset('performance.max_workers')"]


def test_the_hook_notifies_the_shell(prefs):
    preferences, _ = prefs
    seen: list[int] = []
    preferences.on_changed = lambda: seen.append(1)

    preferences.set("performance.gpu_enabled", False)
    preferences.reset()

    assert len(seen) == 2


# --- effects ----------------------------------------------------------------------------

def test_an_applier_is_called_on_registration_and_on_every_change(prefs):
    preferences, _ = prefs
    seen: list[object] = []

    preferences.add_applier("performance.gpu_enabled", seen.append)
    preferences.set("performance.gpu_enabled", False)

    assert seen == [True, False]


def test_the_gpu_follows_the_preference_and_the_environment_overrides_it(monkeypatch, tmp_path):
    from retina import preferences as module
    from retina.backend import xp

    settings = Preferences(path=tmp_path / "p.json")
    monkeypatch.setattr(module, "_source", lambda: settings)
    monkeypatch.delenv("RETINA_GPU", raising=False)

    assert not xp.gpu_disabled()
    settings.set("performance.gpu_enabled", False)
    assert xp.gpu_disabled()
    # The environment variable is a debugging aid: it has to be able to override the setting.
    settings.set("performance.gpu_enabled", True)
    monkeypatch.setenv("RETINA_GPU", "0")
    assert xp.gpu_disabled()


def test_a_stale_temp_folder_is_ignored(monkeypatch, tmp_path):
    """A setting pointing at a folder that has gone must never fail a processing run."""
    from retina import preferences as module

    settings = Preferences(path=tmp_path / "p.json")
    monkeypatch.setattr(module, "_source", lambda: settings)

    assert module.temp_root() is None
    settings.set("folders.temp_dir", str(tmp_path))
    assert module.temp_root() == str(tmp_path)
    settings.set("folders.temp_dir", str(tmp_path / "vanished"))
    assert module.temp_root() is None


# --- application ------------------------------------------------------------------------

def test_the_application_exposes_its_preferences():
    app = Application()

    assert app.preferences.get("performance.max_workers") == 4
    assert app.preferences.set("viewport.readout_probe_size", 5) == 5


def test_viewport_defaults_reach_newly_opened_windows():
    import numpy as np
    from retina.model.image import Image
    from retina.model.viewport_state import MaskDisplayMode

    app = Application()
    app.preferences.set("viewport.mask_display_mode", "overlay_green")
    app.preferences.set("viewport.readout_probe_size", 9)
    try:
        window = app.new_window(Image(np.zeros((8, 8, 1), dtype=np.float32)), window_id="w")

        assert window.viewport.mask_display_mode is MaskDisplayMode.OVERLAY_GREEN
        assert window.viewport.readout.probe_size == 9
    finally:
        app.preferences.reset()


def test_the_default_readout_is_not_shared_between_windows():
    """A default passed by reference would be mutated by the first window that changes it."""
    import numpy as np
    from retina.model.image import Image

    app = Application()
    a = app.new_window(Image(np.zeros((8, 8, 1), dtype=np.float32)), window_id="a")
    b = app.new_window(Image(np.zeros((8, 8, 1), dtype=np.float32)), window_id="b")

    a.viewport.readout.probe_size = 11

    assert b.viewport.readout.probe_size != 11


# --- delegation to the session ----------------------------------------------------------

def test_language_and_reopen_stay_in_the_session():
    """The shell already reads them there: migrating them would have broken what exists."""
    from retina import i18n

    app = Application()
    try:
        assert set(DELEGATED) == {"session.language", "session.reopen"}
        app.preferences.set("session.reopen", True)
        assert app.session.reopen_enabled() is True
        assert app.preferences.get("session.reopen") is True

        app.preferences.set("session.language", "fr")
        assert app.session.language() == "fr"
        app.preferences.set("session.language", "auto")
        assert app.session.language() is None
    finally:
        app.session.set_reopen(False)
        app.session.set_language(None)
        i18n.invalidate()


def test_delegated_keys_are_not_written_to_the_file(tmp_path):
    path = tmp_path / "preferences.json"
    app = Application()
    settings = Preferences(session_provider=lambda: app.session, path=path)
    try:
        settings.set("session.reopen", True)

        assert not path.exists() or "session.reopen" not in path.read_text(encoding="utf-8")
    finally:
        app.session.set_reopen(False)
