"""Process registry: discovery and availability of the built-in processes."""

from __future__ import annotations

from retina.process.registry import ENTRY_POINT_GROUP, all_processes, get, load_builtin


def test_builtins_registered():
    load_builtin()
    ids = set(all_processes())
    assert {
        "GaussianConvolution",
        "HistogramTransformation",
        "CurvesTransformation",
        "PixelMath",
    } <= ids


def test_get_reconstructs_by_id():
    cls = get("PixelMath")
    inst = cls(expression="$T")
    assert inst.process_id == "PixelMath"


def test_all_builtins_are_declared_as_entry_points():
    """A built-in process must be declared in ``pyproject.toml``, not merely imported.

    In an installed wheel the registry is populated through entry points; the import
    fallback of ``load_builtin()`` hides the omission in a source tree, where both paths
    coexist. Three processes (``AutoCrop``, ``Overscan``, ``Script``) lived like that —
    invisible once installed.
    """
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return  # tests run against a wheel, outside the source tree

    declared = set(
        tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["entry-points"][
            ENTRY_POINT_GROUP
        ]
    )
    load_builtin()
    builtins = {
        pid
        for pid, cls in all_processes().items()
        if cls.__module__.startswith("retina.processes")
    }

    assert not (builtins - declared), (
        f"built-in processes not declared as entry points: {sorted(builtins - declared)}"
    )
    assert not (declared - builtins), (
        f"entry points pointing at nothing: {sorted(declared - builtins)}"
    )


def test_entry_points_declared():
    """If the package is installed with its metadata, the entry-point group exists.

    (In an uninstalled source tree the absence is tolerated: the import fallback guarantees
    availability.)
    """
    from importlib.metadata import entry_points

    eps = entry_points(group=ENTRY_POINT_GROUP)
    names = {ep.name for ep in eps}
    if names:  # metadata present (editable install through maturin)
        assert "PixelMath" in names


# --- user process folder ----------------------------------------------------------
def _user_process_source(process_id: str = "UserInvert") -> str:
    return f'''
import numpy as np
from retina.process.base import Process
from retina.process.registry import register


@register
class {process_id}(Process):
    """Test process written "by the user"."""

    process_id = "{process_id}"
    category = "User"
    parameters = []

    def _apply(self, data):
        return np.asarray(1.0 - data)
'''


def test_load_user_registers_a_process(tmp_path):
    """The plugin model without packaging: a .py dropped into the folder is enough."""
    from retina.process.registry import load_user

    (tmp_path / "invert_custom.py").write_text(_user_process_source(), encoding="utf-8")
    failures = load_user(tmp_path)

    assert failures == []
    cls = get("UserInvert")
    assert cls.category == "User"
    # A real module: serialising an instance must find its way back to the source.
    import sys

    assert cls.__module__ in sys.modules


def test_a_broken_file_does_not_penalise_its_neighbours(tmp_path):
    """A draft still being written must never cost the startup."""
    from retina.process.registry import load_user

    (tmp_path / "a_broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "b_valid.py").write_text(
        _user_process_source("UserNeighbour"), encoding="utf-8"
    )
    failures = load_user(tmp_path)

    assert len(failures) == 1 and "a_broken" in failures[0]
    assert "UserNeighbour" in all_processes()


def test_load_user_is_idempotent_and_replaces(tmp_path):
    """Running it again replaces the entry: the "fix it, reload" cycle without a restart."""
    from retina.process.registry import load_user

    file = tmp_path / "evolving.py"
    file.write_text(_user_process_source("UserEvolving"), encoding="utf-8")
    load_user(tmp_path)
    first = get("UserEvolving")

    file.write_text(
        _user_process_source("UserEvolving").replace('"User"', '"UserV2"'), encoding="utf-8"
    )
    load_user(tmp_path)
    second = get("UserEvolving")

    assert second is not first
    assert second.category == "UserV2"


def test_a_missing_folder_is_a_non_event(tmp_path):
    from retina.process.registry import load_user

    assert load_user(tmp_path / "does_not_exist") == []


def test_the_on_changed_hook_is_notified(tmp_path):
    """This is what lets the GUI catalogue follow a process born mid-session."""
    from retina.process import registry

    calls = []
    registry.on_changed = lambda: calls.append(1)
    try:
        (tmp_path / "hooked.py").write_text(_user_process_source("UserHooked"), encoding="utf-8")
        registry.load_user(tmp_path)
    finally:
        registry.on_changed = None

    assert calls, "register() must notify on_changed"
