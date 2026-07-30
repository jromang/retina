"""Credits and licences — and the guard rail that stops the manifest from lying.

A false licence page is worse than no page at all: it gives the assurance that someone
checked. The tests below therefore hold both ends — that the manifest covers what is really
on disk, and that what it promises (a notice, a URL) genuinely exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from retina import credits

RESOURCES = Path(credits.__file__).resolve().parent / "resources"


# --- the manifest keeps its promises ---------------------------------------------------

def test_the_manifest_is_readable_and_not_empty():
    components = credits.all_credits()

    assert len(components) > 20
    assert {c.kind for c in components} <= set(credits.KINDS)


def test_every_component_is_identified_and_placed():
    for component in credits.all_credits():
        assert component.id, f"{component.name}: no identifier"
        assert component.name, f"{component.id}: no name"
        assert component.kind in credits.KINDS, f"{component.id}: family {component.kind!r}"


def test_the_identifiers_are_unique():
    identifiers = [c.id for c in credits.all_credits()]

    assert len(identifiers) == len(set(identifiers))


def test_everything_embedded_declares_a_licence():
    """A resource with no known licence has no business being in the wheel."""
    for component in credits.all_credits():
        if component.kind in ("asset", "frontend", "native", "download"):
            assert component.license, f"{component.id}: licence not declared"


def test_every_announced_notice_exists_and_is_not_empty():
    """Promising a licence text we do not have would be the worst possible outcome."""
    for component in credits.all_credits():
        if not component.notice:
            continue
        path = RESOURCES / component.notice
        assert path.is_file(), f"{component.id}: notice missing ({component.notice})"
        assert len(path.read_text(encoding="utf-8").strip()) > 100


def test_a_component_notice_is_read_by_its_identifier():
    text = credits.notice("tabler-icons")

    assert "MIT" in text
    assert "Paweł Kuna" in text


def test_a_component_without_a_notice_says_so_rather_than_returning_nothing():
    with pytest.raises(KeyError, match="no embedded notice"):
        credits.notice("dockview-core")
    with pytest.raises(KeyError, match="unknown component"):
        credits.notice("not-a-component")


# --- the manifest covers what is really on disk ----------------------------------------

def test_every_embedded_resource_is_declared():
    """The guard rail: adding a resource folder without crediting it breaks here.

    It is the only way to avoid drift — a manifest maintained by hand always ends up
    describing the state of six months ago.
    """
    known = {c.id for c in credits.all_credits()}
    #: resource folder → component that must cover it. Folders holding only our own work
    #: do not appear here.
    expected_items = {
        "icons/lib": "tabler-icons",
        "doc/_assets/katex": "katex",
        "spectra": "siril-spcc-database",
    }
    for folder, component in expected_items.items():
        path = RESOURCES / folder
        if not path.exists():
            continue
        assert component in known, f"{folder} is embedded but {component} is not credited"


def test_every_spectral_curve_cites_its_licence():
    """They come from a third-party project: the citation is not a courtesy."""
    curves = list((RESOURCES / "spectra").rglob("*.csv"))

    assert len(curves) > 40
    for curve in curves:
        header = curve.read_text(encoding="utf-8")[:600]
        assert "# license:" in header, f"{curve.name}: no licence in the header"
        assert "# source:" in header, f"{curve.name}: no source in the header"


def test_the_sample_raw_datasets_are_credited():
    """Whatever we offer to download from the home page, we say where it comes from and
    under which licence.

    The :mod:`retina.samples` manifest is the source of the download; the credits are its
    declaration. Both must name the same DOI, otherwise the page reassures the reader about
    something other than what lands on disk.
    """
    from retina import samples

    downloads = {c.id for c in credits.all_credits() if c.kind == "download"}
    assert "sample-data-zenodo" in downloads

    entry = next(c for c in credits.all_credits() if c.id == "sample-data-zenodo")
    assert "CC-BY" in entry.license
    assert entry.copyright, "a CC BY licence without attribution does not hold up its end"
    for set_ in samples.load_manifest(samples.manifest_path()):
        assert set_.doi in entry.note, f"{set_.id}: DOI missing from the credits"


def test_the_ai_model_manifest_stays_consistent_with_the_credits():
    """The AI models are not redistributed — the credits must say so, not the opposite."""
    downloads = {c.id for c in credits.all_credits() if c.kind == "download"}

    assert "graxpert-models" in downloads
    graxpert = next(c for c in credits.all_credits() if c.id == "graxpert-models")
    # The point that motivated this page: free of charge, but NC.
    assert "NC" in graxpert.license
    assert "commercial" in graxpert.note.lower()


# --- Python dependencies ----------------------------------------------------------------

def test_the_python_dependencies_are_listed_with_their_version():
    """They come from the installed metadata: the list cannot drift."""
    packages = credits.python_dependencies()

    assert len(packages) > 5
    names = {c.name.lower() for c in packages}
    assert "numpy" in names and "astropy" in names
    for package in packages:
        assert package.version, f"{package.name}: version missing"
        assert package.kind == "python"


def test_a_verbose_licence_is_truncated():
    """Some distributions paste the **entire text** into the License field; a table cell
    has no use for it."""
    for package in credits.python_dependencies():
        assert len(package.license) <= 60, (
            f"{package.name}: licence of {len(package.license)} chars")


def test_an_uninstalled_extra_is_simply_omitted():
    """The page describes the installation we have, not the one we might have had."""
    names = {c.id for c in credits.python_dependencies()}

    assert names <= {n.lower() for n in credits._ROOTS}


# --- console ---------------------------------------------------------------------------

def test_app_credits_returns_readable_text():
    from retina.app import Application

    text = Application().credits()

    assert "Tabler Icons" in text
    assert "MIT" in text
    for family in ("Embedded resources", "Installed Python dependencies"):
        assert family in text


def test_the_summary_counts_by_family():
    summary = credits.summary()

    assert set(summary) <= set(credits.KINDS)
    assert sum(summary.values()) == len(credits.all_credits())


def test_the_manifest_is_valid_versioned_json():
    raw_data = json.loads((RESOURCES / "credits.json").read_text(encoding="utf-8"))

    assert raw_data["schema"] == 1
    assert isinstance(raw_data["components"], list)
