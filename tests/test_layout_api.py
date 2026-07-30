"""Console/shell parity of ``app.layout``: usable without a shell (safe no-op) and echoed.

A batch recipe containing ``app.layout.reset()`` must run from the CLI with no GUI;
every write method must emit its Python equivalent (Blender-style).
"""

from __future__ import annotations


def test_layout_headless_noop() -> None:
    from retina import app

    assert app.layout.panels() == []
    assert app.layout.perspectives() == []
    assert app.layout.open_processes() == []
    assert app.layout.is_visible("console") is False
    # no method may raise without a backend
    app.layout.show("console")
    app.layout.hide("console")
    app.layout.toggle("console")
    app.layout.activate("explorer")
    app.layout.save("Custom")
    assert app.layout.load("Custom") is False
    app.layout.delete("Custom")
    app.layout.reset()
    app.layout.lock(True)
    assert app.layout.locked is True
    app.layout.lock(False)
    app.layout.open_process("PixelMath")
    app.layout.close_process("PixelMath")
    # The absence of a shell can no longer be asserted here: `tests/server/` loads aiohttp in
    # the same process. The real guarantee lives in tests/server/test_headless_parity.py,
    # which starts a fresh interpreter.


def test_layout_echo() -> None:
    from retina import app

    echoes: list[str] = []
    previous = app.on_echo
    app.on_echo = echoes.append
    try:
        app.layout.toggle("console")
        app.layout.activate("explorer")
        app.layout.load("Processing")
        app.layout.reset()
        app.layout.lock(True)
        app.layout.lock(False)
        app.layout.open_process("PixelMath")
    finally:
        app.on_echo = previous
    assert "app.layout.toggle('console')" in echoes
    assert "app.layout.activate('explorer')" in echoes
    assert "app.layout.load('Processing')" in echoes
    assert "app.layout.reset()" in echoes
    assert "app.layout.lock(True)" in echoes
    assert "app.layout.open_process('PixelMath')" in echoes
