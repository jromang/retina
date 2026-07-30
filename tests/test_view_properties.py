"""View properties — the receptacle for measurements, and its persistence.

What these tests protect fits in one sentence: a measurement that cost a star detection over
the whole image must not die with the notification that announced it. Previously, ``DynamicPSF``
results lived only inside ``job.done`` — a reconnection, or simply closing the panel, lost them.
They now follow the view and go into the ``.retina`` project.

The design point not to undo is elsewhere: the snapshot publishes only a **summary** (``rev``
and the keys), never the content. Hundreds of stars × N views republished on every
``state.changed`` would cost tens of kilobytes per burst, for data that only an open panel ever
looks at. It is ``app.view_property`` that serves it.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image


@pytest.fixture
def app() -> Application:
    application = Application()
    application.new_window(Image(np.zeros((32, 32, 1), dtype=np.float32)), window_id="Test01")
    return application


@pytest.fixture
def echoes(app: Application) -> list[str]:
    lines: list[str] = []
    app.on_echo = lines.append
    return lines


def test_a_property_is_set_and_read_back(app):
    app.set_view_property("Test01", "psf", {"stars": [{"x": 1.0}]})

    assert app.view_property("Test01", "psf") == {"stars": [{"x": 1.0}]}


def test_none_removes_the_key(app):
    """A missing key and a null key would say the same thing — we keep only one of them."""
    app.set_view_property("Test01", "note", "x")
    app.set_view_property("Test01", "note", None)

    assert app.view("Test01").properties == {}


def test_the_write_counter_advances_on_every_set(app):
    """This is what the snapshot publishes: without it the client would not know to ask again."""
    before = app.view("Test01").properties_rev
    app.set_view_property("Test01", "psf", {"n": 1})
    app.set_view_property("Test01", "psf", {"n": 2})

    assert app.view("Test01").properties_rev == before + 2


def test_setting_a_property_echoes_in_python(app, echoes):
    app.set_view_property("Test01", "psf", {"n": 1})

    assert any("app.set_view_property('Test01', 'psf'" in line for line in echoes)


def test_a_preview_carries_its_own_properties(app):
    """A preview IS a view: it has its own measurements, distinct from its window's."""
    pv = app.new_preview(0, 0, 8, 8, "corner")
    app.set_view_property("Test01", "psf", {"n": 1})
    app.set_view_property(pv.id, "psf", {"n": 2})

    assert app.view_property(pv.id, "psf") == {"n": 2}
    assert app.view_property("Test01", "psf") == {"n": 1}


def test_properties_survive_a_project_round_trip(app, tmp_path):
    """This is the half that counts: without it, reopening a project lost the measurement again."""
    from retina.io.project import load_project, save_project

    app.set_view_property("Test01", "psf", {"n_stars": 3, "fwhm": 2.5})
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    reread = Application()
    load_project(reread, path)

    assert reread.view_property("Test01", "psf") == {"n_stars": 3, "fwhm": 2.5}


def test_a_project_without_properties_is_reread(app, tmp_path):
    """A project saved before this capability must not become unreadable."""
    from retina.io.project import load_project, save_project

    path = str(tmp_path / "empty.retina")
    save_project(app, path)

    reread = Application()
    load_project(reread, path)

    assert reread.view("Test01").properties == {}


def test_the_snapshot_publishes_only_a_summary(app):
    """The content does not cross the snapshot — only enough to know that it has changed."""
    from retina.server.state import SnapshotBuilder

    app.set_view_property("Test01", "psf", {"stars": [{"x": i} for i in range(500)]})
    view = SnapshotBuilder(app).build()["windows"][0]["views"][0]

    assert view["properties"] == {"rev": 1, "keys": ["psf"]}
    assert "stars" not in repr(view), "the data must not enter the snapshot"


def test_a_view_without_properties_does_not_weigh_down_the_snapshot(app):
    from retina.server.state import SnapshotBuilder

    view = SnapshotBuilder(app).build()["windows"][0]["views"][0]

    assert "properties" not in view
