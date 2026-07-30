"""``app.reload`` — re-read the source file into the window, without closing it.

The gesture was missing: a file modified outside the app (another program, a script, a
synchronised folder) forced you to close the window and reopen it, which lost its place in the
layout and its identifier. These tests hold the exact contract: what survives (window, id,
mask, STF of a FITS) and what starts over (history, astrometry, previews).

Headless end to end — pillar #2: no shell is needed in order to reload.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image
from retina.io.fits import save_fits


def _write(path, value: float, obj: str = "M31") -> None:
    save_fits(str(path), Image(np.full((8, 8, 1), value, np.float32)), {"OBJECT": obj})


def test_rereads_the_pixels_and_the_keywords(tmp_path):
    app = Application()
    file = tmp_path / "light.fits"
    _write(file, 0.1, "M31")
    win = app.open(str(file))

    _write(file, 0.9, "M42")
    assert app.reload() is win  # the very same window, not a new one

    assert win.main_view.image.data.mean() == pytest.approx(0.9)
    assert win.keywords["OBJECT"] == "M42"


def test_the_history_starts_over(tmp_path):
    """The previous states describe a file that no longer exists: keeping them would lie."""
    app = Application()
    file = tmp_path / "light.fits"
    _write(file, 0.1)
    win = app.open(str(file))

    view = win.main_view
    view.begin_process("trial")
    view.set_image(Image(np.ones((8, 8, 1), np.float32)))
    view.end_process()
    assert view.can_go_backward

    _write(file, 0.5)
    app.reload()

    assert not view.can_go_backward and not view.can_go_forward
    assert view.history_index == 0
    assert view.image.data.mean() == pytest.approx(0.5)


def test_previews_are_recut_and_astrometry_is_dropped(tmp_path):
    app = Application()
    file = tmp_path / "light.fits"
    _write(file, 0.1)
    win = app.open(str(file))
    preview = win.create_preview(0, 0, 4, 4)
    win.wcs = object()  # as after a PlateSolve

    _write(file, 0.7)
    app.reload()

    # The rectangle is kept, the content comes from the new image.
    assert preview.rect == (0, 0, 4, 4)
    assert preview.image.data.mean() == pytest.approx(0.7)
    # The solution described the old content: keeping it would yield plausible and wrong
    # coordinates, the hardest kind of bug to spot.
    assert win.wcs is None


def test_the_mask_and_the_stf_survive(tmp_path):
    """These are not file content but settings placed on the window."""
    app = Application()
    file = tmp_path / "light.fits"
    _write(file, 0.1)
    win = app.open(str(file))
    mask = Image(np.zeros((8, 8, 1), np.float32))
    win.mask = mask
    stf = win.main_view.compute_auto_stf()

    _write(file, 0.4)
    app.reload()

    assert win.mask is mask
    assert win.main_view.stf is stf


def test_a_different_geometry_is_accepted(tmp_path):
    """The file may have been cropped outside the app — the viewport must follow."""
    app = Application()
    file = tmp_path / "light.fits"
    _write(file, 0.1)
    win = app.open(str(file))
    assert win.viewport.image_size == (8, 8)

    save_fits(str(file), Image(np.zeros((4, 6, 1), np.float32)), {})
    app.reload()

    assert win.main_view.image.width == 6
    assert win.viewport.image_size == (6, 4)


def test_python_echo(tmp_path):
    """Parity pillar: the action returns the executable code that reproduces it."""
    app = Application()
    file = tmp_path / "light.fits"
    _write(file, 0.1)
    win = app.open(str(file))
    echoes: list[str] = []
    app.on_echo = echoes.append

    app.reload()
    assert echoes == ["app.reload()"]

    # A window that is not active is named explicitly: replaying `app.reload()` in a
    # different activation order would not reload the same image.
    other = tmp_path / "other.fits"
    _write(other, 0.2)
    app.open(str(other))
    echoes.clear()
    app.reload(win)
    assert echoes == [f"app.reload(app.windows[{app.windows.index(win)}])"]


def test_readable_refusal_without_a_source_file():
    app = Application()
    app.new_window(Image(np.zeros((4, 4, 1), np.float32)))
    with pytest.raises(RuntimeError, match="nothing to reload"):
        app.reload()


def test_readable_refusal_without_a_window():
    with pytest.raises(RuntimeError, match="No active window"):
        Application().reload()
