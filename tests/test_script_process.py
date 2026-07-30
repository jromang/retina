"""The ``Script`` process — a script run turned into a replayable object.

Modelled on the ``Parameters`` object plus ``Script`` process pairing. What these tests
protect: the **rule that avoids duplication** (an instance is only created if the script
declared itself by exporting a parameter), the **replay** with the memorised values, and the
two guard rails — recursion and file digest.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from retina import Image, parameters
from retina.app import Application
from retina.process.registry import load_builtin

load_builtin()


@pytest.fixture
def fresh_app():
    app = Application()
    app.new_window(Image(np.full((8, 8, 1), 0.5, dtype=np.float32)), window_id="Target")
    return app


def _script_instance(app):
    """The `Script` instance left by the last `run_recipe` on the active view."""
    return next(p for p in app.active_view.history_processes() if p.process_id == "Script")


def _script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body)
    return str(path)


# --- the rule that avoids duplication -------------------------------------------
def test_a_silent_script_leaves_no_instance(tmp_path, fresh_app):
    """A script that applies processes already leaves its history, step by step."""
    path = _script(
        tmp_path,
        "silent.py",
        "from retina import Invert\nInvert().execute_on(app.active_view)\n",
    )
    fresh_app.run_recipe(path)

    labels = fresh_app.active_view.history_labels()
    assert len(labels) == 2  # initial state + Invert, and nothing more
    assert not any("Script" in label for label in labels)


def test_a_script_that_exports_leaves_its_instance(tmp_path, fresh_app):
    path = _script(
        tmp_path,
        "declare.py",
        "retina.parameters.set('factor', 0.25)\n"
        "from retina import PixelMath\n"
        "PixelMath(expression='img * 0.25').execute_on(app.active_view)\n",
    )
    fresh_app.run_recipe(path)

    instances = fresh_app.active_view.history_processes()
    scripts = [p for p in instances if p.process_id == "Script"]
    assert len(scripts) == 1
    assert scripts[0].exported() == {"factor": 0.25}
    assert scripts[0].path == path


def test_the_instance_does_not_touch_the_pixels(tmp_path, fresh_app):
    """It is a replayable marker, not one more transformation."""
    path = _script(tmp_path, "note.py", "retina.parameters.set('nothing', 1)\n")
    before = fresh_app.active_view.image.data.copy()
    fresh_app.run_recipe(path)
    np.testing.assert_array_equal(fresh_app.active_view.image.data, before)


def test_without_an_active_view_nothing_is_recorded(tmp_path):
    """A global script runs; there is simply no history to put it in."""
    app = Application()
    path = _script(tmp_path, "global.py", "retina.parameters.set('x', 1)\n")
    app.run_recipe(path)  # does not raise


# --- replay ---------------------------------------------------------------------
def test_the_replay_recovers_the_parameters(tmp_path, fresh_app):
    """The heart of the mechanism: replaying the instance means re-running the script *as it
    was set up*."""
    path = _script(
        tmp_path,
        "factor.py",
        "from retina import PixelMath\n"
        "f = retina.parameters.get('factor', 1.0)\n"
        "retina.parameters.set('factor', f)\n"
        "PixelMath(expression=f'img * {f}').execute_on(app.active_view)\n",
    )
    # First run: the script takes its default (1.0) and exports it.
    fresh_app.run_recipe(path)
    instance = _script_instance(fresh_app)

    # We set the instance, then replay it: the script must see 0.5, not its default.
    instance.exported_values = '{"factor": 0.5}'
    start = fresh_app.active_view.image.data.copy()
    instance.execute_on(fresh_app.active_view)
    np.testing.assert_allclose(fresh_app.active_view.image.data, start * 0.5, atol=1e-6)


def test_the_replay_pushes_a_single_history_entry(tmp_path, fresh_app):
    """The replayed script does not re-register itself: that would be one instance per
    replay."""
    path = _script(
        tmp_path,
        "unique.py",
        "retina.parameters.set('x', 1)\nfrom retina import Invert\n"
        "Invert().execute_on(app.active_view)\n",
    )
    fresh_app.run_recipe(path)
    instance = _script_instance(fresh_app)

    before = len(fresh_app.active_view.history_labels())
    instance.execute_on(fresh_app.active_view)
    # One entry for the replayed `Script`, one for the `Invert` it applies.
    assert len(fresh_app.active_view.history_labels()) == before + 2


def test_recursion_is_refused(tmp_path, fresh_app):
    """The usual limit: without it, a script that replays itself loops forever."""
    from retina.processes.script import Script

    path = _script(tmp_path, "loop.py", "retina.parameters.set('x', 1)\n")
    fresh_app.run_recipe(path)
    instance = _script_instance(fresh_app)

    replayed = _script(
        tmp_path,
        "replay.py",
        "import json\n"
        "from retina.processes.script import Script\n"
        f"Script(path={path!r}, exported_values='{{}}').execute_on(app.active_view)\n",
    )
    with pytest.raises(RuntimeError, match="recursive"):
        fresh_app.run_recipe(replayed)
    assert isinstance(instance, Script)


def test_the_digest_reports_a_modified_script(tmp_path, fresh_app, capsys):
    """Warn, do not refuse: the script may have been fixed on purpose. Staying silent, on the
    other hand, would run something other than what was recorded."""
    path = _script(tmp_path, "evolved.py", "retina.parameters.set('x', 1)\n")
    fresh_app.run_recipe(path)
    instance = _script_instance(fresh_app)
    assert instance.digest  # taken at recording time

    (tmp_path / "evolved.py").write_text("retina.parameters.set('x', 2)\n")
    capsys.readouterr()
    instance.execute_on(fresh_app.active_view)
    assert "has changed" in capsys.readouterr().out


def test_an_instance_without_a_file_raises(fresh_app):
    from retina.processes.script import Script

    with pytest.raises(ValueError, match="no file"):
        Script(path="").execute_on(fresh_app.active_view)


# --- the parameters object ------------------------------------------------------
def test_parameters_outside_a_script_do_not_raise(tmp_path):
    """Calling a script's function from the console must not blow up."""
    parameters.set("x", 1)  # silently ignored
    assert parameters.get("x") is None
    assert parameters.has("x") is False
    assert parameters.is_view_target is False
    assert parameters.is_global_target is False


def test_the_typed_readers_tolerate_text(tmp_path, fresh_app):
    """A value re-read from XML arrives as text: `bool('false')` is True, and the parameter
    unchecked in the last run would come back checked."""
    path = _script(
        tmp_path,
        "types.py",
        "p = retina.parameters\n"
        "p.set('flag', 'false')\n"
        "p.set('number', '3')\n"
        "assert p.get_bool('flag') is False\n"
        "assert p.get_int('number') == 3\n"
        "assert p.get_real('missing', 1.5) == 1.5\n"
        "assert p.get_int('flag', 7) == 7\n",
    )
    fresh_app.run_recipe(path)


def test_the_script_knows_its_target(tmp_path, fresh_app):
    path = _script(
        tmp_path,
        "target.py",
        "assert retina.parameters.is_view_target\n"
        "assert retina.parameters.target_view.id == 'Target'\n"
        "retina.parameters.set('seen', True)\n",
    )
    fresh_app.run_recipe(path)


def test_a_script_instance_is_serialisable(tmp_path, fresh_app):
    """The parameter used to be called `values` and shadowed the **method**
    `Process.values()`: every Script instance raised a `TypeError` on its first
    serialisation. So it could neither be filed in a library, nor enter a recipe, nor travel
    over the network — that is to say exactly what this process is meant to make possible."""
    from retina.processes.script import Script

    path = _script(tmp_path, "serialize.py", "retina.parameters.set('x', 3)\n")
    fresh_app.run_recipe(path)
    instance = _script_instance(fresh_app)

    rendered = instance.to_dict()

    assert rendered["process_id"] == "Script"
    assert rendered["values"]["path"] == path
    assert json.loads(rendered["values"]["exported_values"]) == {"x": 3}
    assert "Script(" in instance.to_python_source()
    # and the round trip rebuilds an equivalent instance
    assert Script(**rendered["values"]).exported() == {"x": 3}


def test_the_old_serialisation_key_is_still_accepted(tmp_path):
    """An instance filed in a library before the renaming must keep being readable: the
    meaning has not changed, only the parameter name."""
    from retina.processes.script import Script

    instance = Script(path="/tmp/old.py", values='{"a": 1}')

    assert instance.exported() == {"a": 1}
    assert instance.to_dict()["values"]["exported_values"] == '{"a": 1}'
