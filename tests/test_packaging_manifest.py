"""Guard: what the bundle installs must stay in step with what the extras declare.

The processes import scipy, scikit-image and photutils **lazily**, inside method bodies. A
bundle missing those wheels therefore starts, lists its 141 processes, and dies with a
``ModuleNotFoundError`` on the first click. "The app launches" is not a packaging test, and the
failure mode is invisible until a user hits it.

The invariant used to be a paragraph in the packaging notes: the briefcase ``requires`` list is
the mirror of the ``astro`` extra, minus ``astrometry``, which does not compile under MSVC.
Paragraphs drift — this one had already drifted once. Here it is a test.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
EXTRAS = PYPROJECT["project"]["optional-dependencies"]
BRIEFCASE = PYPROJECT["tool"]["briefcase"]["app"]["retina"]


def _names(requirements) -> set[str]:
    """Distribution names, without the version specifiers, lowercased and normalized."""
    out = set()
    for requirement in requirements:
        name = requirement.split(";")[0].split("[")[0]
        for operator in (">=", "==", "<=", "~=", "!=", ">", "<"):
            name = name.split(operator)[0]
        out.add(name.strip().lower().replace("_", "-"))
    return out


def test_astro_msvc_is_astro_without_astrometry():
    """The Windows extra differs from the portable one by exactly one package."""
    difference = _names(EXTRAS["astro"]) - _names(EXTRAS["astro-msvc"])

    assert difference == {"astrometry"}, (
        "astro-msvc must be astro minus astrometry (which does not build under MSVC); "
        f"it currently also drops {sorted(difference - {'astrometry'})}"
    )
    assert not _names(EXTRAS["astro-msvc"]) - _names(EXTRAS["astro"]), (
        "astro-msvc holds packages absent from astro"
    )


def test_the_bundle_carries_the_whole_astro_ecosystem():
    """Every lazily-imported dependency must be in the bundle, or a process dies on first use."""
    missing = _names(EXTRAS["astro-msvc"]) - _names(BRIEFCASE["requires"])

    assert missing == set(), (
        "packages in the astro-msvc extra but absent from [tool.briefcase] requires:\n  "
        + "\n  ".join(sorted(missing))
        + "\nA bundle without them starts, shows its processes, and fails on the first click."
    )


def test_the_bundle_carries_the_web_shell_and_projects():
    """The bundle serves its own UI and opens .retina projects; both need their wheels."""
    required = _names(BRIEFCASE["requires"])
    for extra in ("web", "project", "xisf"):
        missing = _names(EXTRAS[extra]) - required
        assert missing == set(), f"[{extra}] packages absent from the bundle: {sorted(missing)}"


def test_astrometry_is_reintroduced_off_windows():
    """It does not build under MSVC, but it is the offline plate-solver everywhere else."""
    for platform in ("linux", "macOS"):
        extra = BRIEFCASE.get(platform, {}).get("requires", [])
        assert "astrometry" in _names(extra), (
            f"[tool.briefcase.app.retina.{platform}] must reintroduce astrometry"
        )


@pytest.mark.parametrize("key", ["version", "bundle", "url", "license"])
def test_the_briefcase_identity_is_declared(key):
    assert PYPROJECT["tool"]["briefcase"].get(key), f"[tool.briefcase] {key} is missing"


def test_the_versions_agree():
    """Three manifests carry a version; a release is cut from the briefcase one."""
    assert PYPROJECT["project"]["version"] == PYPROJECT["tool"]["briefcase"]["version"]


def test_the_embedded_runtime_is_pinned():
    """Without support_revision, briefcase takes its template's value.

    That is not a detail: the same number governs the OpenSSL shipped in the MSI, because
    libssl-3.dll comes out of the same archive as the Python DLL. It is the single line to move
    for a Python *or* an OpenSSL advisory.
    """
    windows = BRIEFCASE.get("windows", {})
    assert windows.get("support_revision"), (
        "[tool.briefcase.app.retina.windows] support_revision must stay pinned"
    )
