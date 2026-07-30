"""Headless parity of the web shell.

The project's "headless first" pillar says that ``import retina`` must work **without a
shell**: opening images, applying processes, saving — in a plain script, on a machine with no
display. The web shell is an optional facade and must stay invisible to the domain. Without
this test, a creeping dependency (a ``from .server import ...`` slipped into ``app.py``) would
turn aiohttp into a de facto dependency of image processing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _run(code: str) -> str:
    """Run a snippet in a fresh interpreter — an import is irreversible in ours."""
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_importing_retina_does_not_pull_in_the_shell():
    """The core stays pure: neither the web shell nor its dependencies.

    ``h5py`` is on the list for the same reason: the project format is an extra
    (``[project]``), and an ``import retina`` on a compute server must not require an HDF5
    library just to apply a process.
    """
    result = _run(
        "import retina, sys;"
        "print(sorted(m for m in ('aiohttp', 'IPython', 'markdown', 'h5py')"
        "             if m in sys.modules))"
    )
    assert result == "[]", f"shell modules pulled in by import retina: {result}"


def test_translation_does_not_depend_on_babel():
    """``retina.i18n`` translates with ``gettext`` (standard library), never with Babel.

    Babel is a **development** dependency: it extracts and compiles the catalogues
    (``scripts/update_translations.py``). Letting it into the runtime would make the domain
    depend on a translation tool just to display a label — and a deployment without the
    ``[dev]`` extra would no longer start.
    """
    result = _run(
        "import retina.i18n as i, sys;"
        "print(i.effective_language() in i.LANGUAGES, 'babel' in sys.modules)"
    )
    assert result == "True False", result


def test_the_project_module_is_importable_without_h5py():
    """Naming ``retina.io.project`` (introspection, tooling) must cost nothing: h5py is only
    loaded on the first ``save_project``/``load_project``."""
    result = _run("import retina.io.project, sys; print('h5py' in sys.modules)")
    assert result == "False"


def test_importing_retina_does_not_pull_in_the_server_package():
    result = _run(
        "import retina, sys; print([m for m in sys.modules if m.startswith('retina.server')])"
    )
    assert result == "[]", f"shell packages imported: {result}"


def test_the_server_package_is_importable_without_aiohttp():
    """``import retina.server`` must cost nothing as long as nobody asks for ``ServerApp``.

    The module has a lazy ``__getattr__`` for exactly that reason: naming the package
    (introspection, entry points, tooling) must not load the HTTP stack.
    """
    result = _run("import retina.server, sys; print('aiohttp' in sys.modules)")
    assert result == "False"


def test_running_a_recipe_stays_shell_free():
    """The batch path (``python -m retina.run``) must pull in no shell at all."""
    result = _run(
        "import retina;"
        "from retina.model.image import Image;"
        "import numpy as np, sys;"
        "img = Image(np.zeros((8, 8, 1), dtype=np.float32));"
        "retina.app.new_window(img);"
        "retina.app.compute_auto_stf();"
        "print('aiohttp' in sys.modules or any(m.startswith('retina.server')"
        "      for m in sys.modules))"
    )
    assert result == "False"


def test_the_package_entry_point_exists():
    """``python -m retina`` must start — it is the packaged app's entry point.

    Briefcase runs the executable installed by ``python -m retina`` and that name is not
    configurable (``AppConfig.main_module()`` returns ``module_name`` verbatim). Deleting
    ``retina/__main__.py`` would therefore break the installer, with no other test noticing.
    """
    out = subprocess.run(
        [sys.executable, "-m", "retina", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert out.returncode == 0, out.stderr
    assert "--no-shell" in out.stdout, out.stdout


def test_the_entry_point_does_not_pollute_the_import():
    """``__main__.py`` must never be loaded by a plain ``import retina``."""
    result = _run("import retina, sys; print('retina.__main__' in sys.modules)")
    assert result == "False"


@pytest.mark.parametrize("module", ["retina.server.core", "retina.server.security"])
def test_server_modules_are_importable(module: str):
    """Baseline guard: the web shell modules import (with the [web] extra installed)."""
    pytest.importorskip("aiohttp", reason="[web] extra missing")
    _run(f"import {module}; print('ok')")


def test_the_mcp_stdio_entry_point_exists():
    """``python -m retina.mcp`` is the configuration a Claude Desktop user pastes: renaming
    it would break configuration files living outside this repository."""
    out = subprocess.run(
        [sys.executable, "-m", "retina.mcp", "--help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert out.returncode == 0, out.stderr
    assert "stdio" in out.stdout


def test_importing_retina_does_not_pull_in_the_mcp_server():
    """MCP is a client of the API like any other: the domain ignores it."""
    result = _run(
        "import retina, sys; print([m for m in sys.modules if 'mcp' in m])"
    )
    assert result == "[]", f"MCP modules pulled in by import retina: {result}"
