"""User session — recent items and automatic reopening."""

from __future__ import annotations

import json
import os

import pytest
from retina.session import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "session.json", limit=3)


def test_recents_are_at_the_top_and_bounded(store, tmp_path):
    for name in ("a", "b", "c", "d"):
        store.add_recent_file(str(tmp_path / name))

    recents = store.recent_files()

    assert len(recents) == 3
    assert recents[0].endswith("d")
    assert not any(p.endswith("a") for p in recents)


def test_reopening_a_file_moves_it_up_without_duplicating_it(store, tmp_path):
    store.add_recent_file(str(tmp_path / "a"))
    store.add_recent_file(str(tmp_path / "b"))

    store.add_recent_file(str(tmp_path / "a"))

    # `os.path.basename`, not a split on "/": the remembered paths are the platform's own, and
    # on Windows the separator is "\" — the split returned the whole path.
    assert [os.path.basename(p) for p in store.recent_files()] == ["a", "b"]


def test_paths_are_resolved(store, tmp_path, monkeypatch):
    """Otherwise `./m31.fits` and `/data/m31.fits` would appear twice, and clicking the first
    would depend on the server's current directory."""
    (tmp_path / "m31.fits").write_bytes(b"")
    monkeypatch.chdir(tmp_path)

    store.add_recent_file("./m31.fits")
    store.add_recent_file(str(tmp_path / "m31.fits"))

    assert store.recent_files() == [str(tmp_path / "m31.fits")]


def test_files_and_projects_are_two_lists(store, tmp_path):
    store.add_recent_file(str(tmp_path / "image.fits"))
    store.add_recent_project(str(tmp_path / "project.retina"))

    assert len(store.recent_files()) == 1
    assert len(store.recent_projects()) == 1
    assert store.recent_files() != store.recent_projects()


def test_forget_removes_from_both_lists(store, tmp_path):
    path = str(tmp_path / "x")
    store.add_recent_file(path)
    store.add_recent_project(path)

    store.forget(path)

    assert store.recent_files() == [] and store.recent_projects() == []


def test_a_corrupt_file_yields_an_empty_session(tmp_path):
    """Losing a list of recents is harmless; refusing to start because of it would be
    absurd."""
    path = tmp_path / "session.json"
    path.write_text("{ this is not JSON")
    store = SessionStore(path)

    assert store.recent_files() == []
    assert store.reopen_enabled() is False

    store.add_recent_file(str(tmp_path / "a"))  # and writing repairs it
    assert len(store.recent_files()) == 1


def test_reopening_is_disabled_by_default(store):
    """A project embeds every history state: writing it on close without being asked would be
    an unpleasant surprise."""
    assert store.reopen_enabled() is False

    store.set_reopen(True)
    assert store.reopen_enabled() is True


def test_the_on_changed_hook_is_called_on_every_mutation(store, tmp_path):
    calls = []
    store.on_changed = lambda: calls.append(1)

    store.add_recent_file(str(tmp_path / "a"))
    store.set_reopen(True)

    assert len(calls) == 2


def test_state_describes_everything_the_welcome_screen_needs(store, tmp_path):
    store.add_recent_file(str(tmp_path / "a.fits"))
    store.add_recent_project(str(tmp_path / "p.retina"))

    state = store.state()

    assert set(state) == {"recent_files", "recent_projects", "reopen", "has_autosession",
                         "language", "effective_language"}
    assert state["reopen"] is False and state["has_autosession"] is False


def test_the_write_is_versioned(store, tmp_path):
    store.set_reopen(True)

    data = json.loads((tmp_path / "session.json").read_text())

    assert data["version"] == 1
