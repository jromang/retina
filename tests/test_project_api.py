"""``app.save_project`` / ``app.open_project`` — console parity.

Pillar #2 demands that everything be doable from the console: these tests replay the format's
scenario (tests/test_project_io.py) going **only** through the ``app.*`` API, and check that
each gesture echoes as replayable Python.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("h5py")
pytest.importorskip("astropy")

from retina.app import Application
from retina.model.image import Image
from retina.process.registry import load_builtin
from retina.session import SessionStore

load_builtin()


@pytest.fixture
def app(tmp_path):
    """A fresh Application, with its session isolated in the test's tmp_path."""
    application = Application()
    application._session = SessionStore(tmp_path / "session.json")
    return application


def _image(seed: int = 0) -> Image:
    rng = np.random.default_rng(seed)
    return Image(rng.random((8, 6, 1)).astype(np.float32))


def _echoes(app) -> list[str]:
    log: list[str] = []
    app.on_echo = log.append
    return log


# --- console parity ----------------------------------------------------------------------

def test_the_whole_cycle_is_doable_from_the_console(app, tmp_path):
    from retina.processes.channels import Invert

    win = app.new_window(_image(1), window_id="Image01")
    Invert().execute_on(win.main_view)
    path = str(tmp_path / "m31.retina")

    app.save_project(path)

    fresh = Application()
    fresh._session = SessionStore(tmp_path / "s2.json")
    report = fresh.open_project(path)

    assert report.windows == ["Image01"]
    assert fresh.windows[0].main_view.history_labels() == ["initial", "Invert"]
    assert fresh.project_path == path


def test_every_gesture_is_echoed_as_replayable_python(app, tmp_path):
    app.new_window(_image(), window_id="Image01")
    path = str(tmp_path / "p.retina")
    log = _echoes(app)

    app.save_project(path)
    app.open_project(path)
    app.close_project()

    assert f"app.save_project({path!r})" in log
    assert f"app.open_project({path!r})" in log
    assert "app.close_project()" in log


def test_the_added_suffix_appears_in_the_echo(app, tmp_path):
    """The echo must name the file actually written, not the one that was asked for."""
    app.new_window(_image(), window_id="Image01")
    log = _echoes(app)

    summary = app.save_project(str(tmp_path / "no_suffix"))

    assert summary["path"].endswith(".retina")
    assert f"app.save_project({summary['path']!r})" in log


# --- current project ---------------------------------------------------------------------

def test_saving_again_without_a_path_reuses_the_current_project(app, tmp_path):
    from retina.processes.channels import Invert

    app.new_window(_image(), window_id="Image01")
    path = str(tmp_path / "p.retina")
    app.save_project(path)

    Invert().execute_on(app.windows[0].main_view)
    app.save_project()

    fresh = Application()
    fresh._session = SessionStore(tmp_path / "s2.json")
    fresh.open_project(path)
    assert fresh.windows[0].main_view.history_labels() == ["initial", "Invert"]


def test_without_a_current_project_saving_requires_a_path(app):
    app.new_window(_image(), window_id="Image01")

    with pytest.raises(ValueError, match="give a path"):
        app.save_project()


def test_closing_the_project_empties_the_session(app, tmp_path):
    app.new_window(_image(), window_id="Image01")
    app.save_project(str(tmp_path / "p.retina"))

    app.close_project()

    assert app.windows == []
    assert app.active_window is None
    assert app.project_path is None
    assert app.project_documents() is None


# --- the documents blob, opaque to the domain --------------------------------------------

def test_the_shell_blob_survives_a_console_that_ignores_it(app, tmp_path):
    """`open_project` then `save_project` from a pure console must not make the user lose
    their tabs and their unsaved buffers."""
    app.new_window(_image(), window_id="Image01")
    path = str(tmp_path / "p.retina")
    blob = {"version": 1, "scripts": {"docs": [{"id": "script:1", "text": "x = 1"}]}}
    app.save_project(path, documents=blob)

    console = Application()
    console._session = SessionStore(tmp_path / "s2.json")
    console.open_project(path)
    console.save_project()  # no blob passed: the project's own must survive

    third = Application()
    third._session = SessionStore(tmp_path / "s3.json")
    assert third.open_project(path).documents == blob


def test_set_project_documents_is_not_echoed(app):
    """It is a report from the client, not a user action: echoing it would fill the console
    with one line per keystroke in a script editor."""
    log = _echoes(app)

    app.set_project_documents({"version": 1})

    assert log == []
    assert app.project_documents() == {"version": 1}


# --- recents ------------------------------------------------------------------------------

def test_opening_an_image_feeds_the_recent_files(app, tmp_path):
    from retina.io.fits import save_fits

    path = str(tmp_path / "m31.fits")
    save_fits(path, _image())

    app.open(path)

    assert app.recent_files() == [path]
    assert app.recent_projects() == []


def test_saving_and_opening_a_project_feed_the_recent_projects(app, tmp_path):
    app.new_window(_image(), window_id="Image01")
    path = str(tmp_path / "p.retina")

    app.save_project(path)
    app.open_project(path)

    assert app.recent_projects() == [path]
    assert app.recent_files() == []


# --- the restoration order: views before recipes ------------------------------------------

def test_a_masked_recipe_runs_after_reopening(app, tmp_path):
    """The per-step masks of a `ProcessContainer` designate views **by identifier**, resolved
    at execution time. A project must therefore restore its views before its recipes become
    replayable, otherwise the first masked step would raise "mask not found"."""
    from retina.process.container import ProcessContainer
    from retina.processes.channels import Invert

    target = app.new_window(_image(1), window_id="Target01")
    app.new_window(_image(2), window_id="Mask01")
    path = str(tmp_path / "p.retina")
    app.save_project(path)

    fresh = Application()
    fresh._session = SessionStore(tmp_path / "s2.json")
    fresh.open_project(path)

    recipe = ProcessContainer([Invert()])
    recipe.set_mask(0, "Mask01")
    recipe.execute_on(fresh.view("Target01"),
                      resolve_mask=lambda vid: fresh.view(vid).image)

    assert fresh.view("Target01").history_labels() == ["initial", "Invert"]
    assert target is not fresh.windows[0]  # really the restored session, not the old one


def test_a_recipe_masked_by_a_restored_preview(app, tmp_path):
    """Same thing with a preview: it only exists after step 3 of the loading."""
    from retina.process.container import ProcessContainer
    from retina.processes.channels import Invert

    win = app.new_window(_image(1), window_id="Target01")
    other = app.new_window(_image(2), window_id="Source01")
    other.create_preview(0, 0, 6, 8, preview_id="Source01_Zone")
    path = str(tmp_path / "p.retina")
    app.save_project(path)

    fresh = Application()
    fresh._session = SessionStore(tmp_path / "s2.json")
    fresh.open_project(path)

    recipe = ProcessContainer([Invert()])
    recipe.set_mask(0, "Source01_Zone")
    recipe.execute_on(fresh.view("Target01"),
                      resolve_mask=lambda vid: fresh.view(vid).image)

    assert fresh.view("Target01").history_labels() == ["initial", "Invert"]
    assert win.id == "Target01"
