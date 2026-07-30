"""``app.run_recipe`` — running a **file**, as opposed to the console buffer.

The two gestures coexist and do not serve the same purpose. ``console.execute`` sends text to
the shared interpreter: the variables stay available at the prompt, which is the whole point
of an editor attached to live state. ``app.run_recipe`` runs a file in a fresh namespace, with
``__file__`` set — like ``python -m retina.run``.

The method had always existed in the domain and was only reachable by typing at the console:
the interface advertised `app.run_recipe(path)` while doing something else entirely.
"""

from __future__ import annotations

import pytest
from rpcsession import RpcFailure


async def test_it_runs_a_file_and_acts_on_the_domain(session, domain, tmp_path):
    recipe = tmp_path / "recipe.py"
    recipe.write_text(
        "import numpy as np\n"
        "from retina.model.image import Image\n"
        "app.new_window(Image(np.zeros((4, 4, 1), dtype=np.float32)), window_id='FromRecipe')\n"
    )
    await session.call("app.run_recipe", path=str(recipe))
    assert any(w.id == "FromRecipe" for w in domain.windows)


async def test_the_file_knows_its_own_path(session, tmp_path):
    """``__file__`` is set: a recipe can resolve its resources relative to itself."""
    recipe = tmp_path / "where_am_i.py"
    control = tmp_path / "witness.txt"
    recipe.write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('witness.txt').write_text(__file__)\n"
    )
    await session.call("app.run_recipe", path=str(recipe))
    assert control.read_text() == str(recipe)


async def test_a_fresh_namespace_on_every_call(session, tmp_path):
    """Unlike the console, one recipe does not see what another one left behind."""
    writer = tmp_path / "writer.py"
    writer.write_text("marker = 1\n")
    reader = tmp_path / "reader.py"
    reader.write_text("marker\n")

    await session.call("app.run_recipe", path=str(writer))
    with pytest.raises(RpcFailure):
        await session.call("app.run_recipe", path=str(reader))


async def test_the_recipe_echoes_its_call_in_the_console(session, tmp_path):
    """The echo goes out **before** the run: a recipe that fails still leaves its line."""
    recipe = tmp_path / "boom.py"
    recipe.write_text("raise ValueError('boom')\n")
    session.clear()
    with pytest.raises(RpcFailure):
        await session.call("app.run_recipe", path=str(recipe))
    await session.drain()

    echoes = [e["code"] for e in session.of("echo")]
    assert f"app.run_recipe({str(recipe)!r})" in echoes


async def test_an_error_in_a_recipe_surfaces_as_an_rpc_error(session, tmp_path):
    recipe = tmp_path / "broken.py"
    recipe.write_text("1 / 0\n")
    with pytest.raises(RpcFailure) as error:
        await session.call("app.run_recipe", path=str(recipe))
    assert "ZeroDivision" in str(error.value)


async def test_a_missing_file_is_refused_cleanly(session, tmp_path):
    with pytest.raises(RpcFailure):
        await session.call("app.run_recipe", path=str(tmp_path / "missing.py"))
