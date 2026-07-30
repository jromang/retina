"""Volatile semantics of previews — the try-out loop without Undo (headless)."""

from __future__ import annotations

import numpy as np
from retina.model.image import Image
from retina.model.window import ImageWindow
from retina.process.base import Process


class _Double(Process):
    process_id = "DoubleTest"
    parameters = []

    def _apply(self, data):
        return data * 2.0


def _window() -> ImageWindow:
    data = np.full((32, 32, 1), 0.1, dtype=np.float32)
    return ImageWindow(Image(data), window_id="T01")


def test_volatile_reapply_resets_to_base() -> None:
    win = _window()
    pv = win.create_preview(0, 0, 16, 16)
    assert pv.volatile
    _Double().execute_on(pv)
    _Double().execute_on(pv)  # re-applying = start again from the base, NOT accumulate
    assert np.allclose(pv.image.data, 0.2)
    assert pv.history_labels() == ["initial", "DoubleTest"]  # never stacks up


def test_store_makes_history_cumulative() -> None:
    win = _window()
    pv = win.create_preview(0, 0, 16, 16)
    pv.store()
    _Double().execute_on(pv)
    _Double().execute_on(pv)
    assert np.allclose(pv.image.data, 0.4)  # accumulation after store()
    assert len(pv.history_labels()) == 3


def test_volatile_base_follows_main_view() -> None:
    win = _window()
    pv = win.create_preview(0, 0, 16, 16)
    _Double().execute_on(win.main_view)  # the main view moves on (0.1 → 0.2)
    _Double().execute_on(pv)  # the preview starts again from the NEW base
    assert np.allclose(pv.image.data, 0.4)


def test_set_rect_resyncs_shape() -> None:
    win = _window()
    pv = win.create_preview(0, 0, 16, 16)
    pv.set_rect((4, 4, 12, 20))
    assert pv.image.data.shape == (16, 8, 1)
    assert pv.rect == (4, 4, 12, 20)


def test_rename_and_delete_preview() -> None:
    win = _window()
    pv = win.create_preview(0, 0, 8, 8)
    win.set_current_view(pv)
    win.rename_preview(pv.id, "Background")
    assert win.preview_by_id("Background") is pv and pv.id == "Background"
    win.delete_preview("Background")
    assert win.preview_by_id("Background") is None
    assert win.current_view is win.main_view  # falls back to the main view


def test_app_preview_api_echoes() -> None:
    from retina import app

    echoes: list[str] = []
    previous, app.on_echo = app.on_echo, echoes.append
    win = app.new_window(Image(np.full((32, 32, 1), 0.1, dtype=np.float32)))
    try:
        pv = app.new_preview(0, 0, 16, 16)
        app.select_view(pv.id)
        assert win.current_view is pv
        app.modify_preview(pv.id, 2, 2, 10, 10)
        app.store_preview(pv.id)
        assert not pv.volatile
        app.rename_preview(pv.id, "Zone")
        assert app.view("Zone") is pv
        app.delete_preview("Zone")
    finally:
        app.on_echo = previous
        app.windows.remove(win)
        app._active = app.windows[-1] if app.windows else None
    joined = "\n".join(echoes)
    for needle in ("app.select_view(", "app.modify_preview(", "app.store_preview(",
                   "app.rename_preview(", "app.delete_preview("):
        assert needle in joined, f"missing echo: {needle}"
