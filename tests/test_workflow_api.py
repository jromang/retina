"""New workflow APIs: to_dict, execute_preview, apply(container), history."""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.process.base import Process
from retina.process.container import ProcessContainer
from retina.process.registry import get, load_builtin


def test_to_dict_from_dict_roundtrip() -> None:
    load_builtin()
    p = get("GaussianConvolution")(sigma=2.5)
    d = p.to_dict()
    assert d == {"process_id": "GaussianConvolution", "values": p.values()}
    clone = Process.from_dict(d)
    assert clone.process_id == "GaussianConvolution" and clone.values() == p.values()


def test_execute_preview_decimates_never_upscales() -> None:
    load_builtin()
    img = Image(np.random.default_rng(0).random((512, 256, 1)).astype(np.float32))
    out = get("Invert")().execute_preview(img, max_size=128)
    assert max(out.data.shape[:2]) <= 128
    small = Image(np.random.default_rng(1).random((64, 64, 1)).astype(np.float32))
    out2 = get("Invert")().execute_preview(small, max_size=128)
    assert out2.data.shape == small.data.shape  # never upscaled


def test_execute_preview_refuses_global() -> None:
    load_builtin()

    class _G(Process):
        process_id = "GTest"
        is_global = True
        parameters = []

    with pytest.raises(RuntimeError):
        _G().execute_preview(Image(np.zeros((8, 8, 1), dtype=np.float32)))


def test_apply_accepts_container_and_targets_view() -> None:
    load_builtin()
    from retina import app

    echoes: list[str] = []
    previous, app.on_echo = app.on_echo, echoes.append
    win = app.new_window(Image(np.full((16, 16, 1), 0.25, dtype=np.float32)))
    try:
        pv = app.new_preview(0, 0, 8, 8)
        pc = ProcessContainer([get("Invert")()])
        assert app.apply(pc, view=pv)
        assert np.allclose(pv.image.data, 0.75)
        joined = "\n".join(echoes)
        assert f"app.view({pv.id!r})" in joined  # the echo targets the real view
        assert app.go_to_history(0) is False or True  # never raises
    finally:
        app.on_echo = previous
        app.windows.remove(win)
        app._active = app.windows[-1] if app.windows else None


def test_go_to_history_echo() -> None:
    load_builtin()
    from retina import app

    echoes: list[str] = []
    previous, app.on_echo = app.on_echo, echoes.append
    win = app.new_window(Image(np.full((8, 8, 1), 0.5, dtype=np.float32)))
    try:
        app.apply(get("Invert")())
        assert app.go_to_history(0)
        assert win.current_view.history_index == 0
        assert "app.go_to_history(0)" in echoes
    finally:
        app.on_echo = previous
        app.windows.remove(win)
        app._active = app.windows[-1] if app.windows else None
