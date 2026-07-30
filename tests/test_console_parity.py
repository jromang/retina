"""Console/shell parity: the whole spike pipeline runs WITHOUT ever importing the shell.

This is the test that protects pillar #2 (console completeness). No GUI-only capability must
be needed to open, stretch, process or save.
"""

from __future__ import annotations

import numpy as np
from retina import Application, GaussianConvolution, Image


def test_full_pipeline_headless(tmp_path, capsys):
    app = Application()

    # Blender-style echo: we capture the Python equivalent of every action
    echoed: list[str] = []
    app.on_echo = echoed.append

    # 1) create a window from an image (equivalent to opening one)
    img = Image((np.random.default_rng(1).random((40, 50, 1)) * 0.4).astype(np.float32))
    win = app.new_window(img)
    app.set_active_window(win)

    # 2) auto-stretch (non-destructive STF)
    stf = app.active_view.compute_auto_stf()
    assert stf is app.active_view.stf

    # 3) apply a process through the app API (as a GUI button would)
    app.apply(GaussianConvolution(sigma=2.0))
    assert app.active_view.history_index == 1

    # 4) undo / redo
    assert app.undo()
    assert app.active_view.history_index == 0
    assert app.redo()

    # 5) save as FITS
    out = str(tmp_path / "out.fits")
    app.save(out)

    # the echo does contain the replayable Python code
    joined = "\n".join(echoed)
    assert "GaussianConvolution(sigma=2.0).execute_on(app.active_view)" in joined
    assert "app.save(" in joined

    # The absence of the shell can no longer be asserted here: `tests/server/` loads aiohttp
    # in the same process. The real guarantee lives in tests/server/test_headless_parity.py,
    # which spawns a fresh interpreter.


def test_recipe_execution(tmp_path):
    """`app.run_recipe` runs a script with app + retina in context, without the shell."""
    recipe = tmp_path / "recipe.py"
    recipe.write_text(
        "import numpy as np\n"
        "img = retina.Image((np.ones((8, 8, 1), dtype='float32') * 0.5))\n"
        "app.new_window(img)\n"
        "retina.GaussianConvolution(sigma=1.0).execute_on(app.active_view)\n"
        "assert app.active_view.history_index == 1\n"
    )
    app = Application()
    app.run_recipe(str(recipe))
    assert app.active_view is not None
