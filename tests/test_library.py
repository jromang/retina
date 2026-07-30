"""Library of recipes/instances — on-disk persistence, headless."""

from __future__ import annotations

from retina.library import Library
from retina.process.container import ProcessContainer
from retina.process.registry import get, load_builtin


def _lib(tmp_path, echoes=None):
    return Library(root_dir=str(tmp_path / "lib"),
                   echo=echoes.append if echoes is not None else None)


def test_instance_roundtrip(tmp_path) -> None:
    load_builtin()
    lib = _lib(tmp_path)
    lib["Soft blur"] = get("GaussianConvolution")(sigma=3.5)
    assert "Soft blur" in lib and lib.kind("Soft blur") == "instance"
    item = lib["Soft blur"]
    assert item.process_id == "GaussianConvolution"
    assert item.values()["sigma"] == 3.5


def test_container_roundtrip(tmp_path) -> None:
    load_builtin()
    lib = _lib(tmp_path)
    pc = ProcessContainer([get("Invert")(), get("GaussianConvolution")(sigma=2.0)])
    lib["Pipeline"] = pc
    assert lib.kind("Pipeline") == "container"
    loaded = lib["Pipeline"]
    assert isinstance(loaded, ProcessContainer)
    assert [p.process_id for p in loaded] == ["Invert", "GaussianConvolution"]


def test_rename_delete_positions_and_echo(tmp_path) -> None:
    load_builtin()
    echoes: list[str] = []
    lib = _lib(tmp_path, echoes)
    lib["A"] = get("Invert")()
    lib.rename("A", "B")
    assert lib.names() == ["B"]
    assert lib.position("B") is None
    lib.move("B", 120.0, 48.0)
    assert lib.position("B") == (120.0, 48.0)
    # replacing the content preserves the position (stable desktop icon)
    lib["B"] = get("GaussianConvolution")(sigma=1.0)
    assert lib.position("B") == (120.0, 48.0)
    del lib["B"]
    assert len(lib) == 0
    joined = "\n".join(echoes)
    assert "app.library['A'] = Invert()" in joined
    assert "app.library.rename('A', 'B')" in joined
    assert "app.library.move('B', 120.0, 48.0)" in joined
    assert "del app.library['B']" in joined


def test_on_changed_hook_and_headless(tmp_path) -> None:
    load_builtin()
    lib = _lib(tmp_path)
    count = {"n": 0}
    lib.on_changed = lambda: count.__setitem__("n", count["n"] + 1)
    lib["X"] = get("Invert")()
    del lib["X"]
    assert count["n"] == 2
    # The absence of the shell can no longer be asserted here: `tests/server/` loads aiohttp
    # in the same process. The real guarantee lives in tests/server/test_headless_parity.py,
    # which spawns a fresh interpreter.
