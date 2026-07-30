"""Guard: the source stays English, and the French catalogues stay French.

The mirror image of ``test_i18n_guard.py``. That one protects the *catalogues* — every UI label
must reach them. This one protects the *source* — no French may reach it. Both exist because
the project is bilingual on purpose, and the boundary between the two is not something a reader
can be expected to keep in mind.

The convention was inverted in July 2026, when the project was published: code comments used to
be French. A rule that changed once can change back by accident, so it is a test rather than a
paragraph. Three probes, because no single one is sufficient:

1. **accented characters** catch the bulk of it, but neither necessarily nor sufficiently:
   English technical prose has accents too (``a-trous``, ``Perez``, ``moire``), and plenty of
   French carries none;
2. **French bigrams and elisions** catch the accent-free residue. Single stopwords were tried
   first and abandoned — ``la``, ``si``, ``on``, ``est``, ``pas`` collide with English and with
   code far too often to be usable;
3. **French identifiers**, by AST walk. This one has no textual signature at all: ``taille`` is
   pure ASCII and reads as a plausible English token to every other check in the repository.

What the rule deliberately does **not** cover is listed in ``scripts/check_english.py`` — the
two message catalogues, the French half of the per-process documentation, ``README.fr.md``, the
assertions that verify the catalogues render French, and the French key aliases in
``keybindings.ts``, which are a feature.

The implementation lives in ``scripts/check_english.py`` so that it can also be run by hand
during a migration, where a burn-down number is more useful than a pass/fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

check_english = pytest.importorskip("check_english")


@pytest.fixture(scope="module")
def report():
    report = check_english.Report()
    for path in check_english.tracked_files():
        check_english.probe_text(path, report)
        if path.suffix == ".py":
            check_english.probe_identifiers(path, report)
    return report


def _format(offenders) -> str:
    return "\n  ".join(f"{o.path}:{o.line} ({o.where}) {o.excerpt}" for o in offenders[:40])


def test_no_accented_french_outside_the_catalogues(report):
    """An accent in a comment or a docstring is French that escaped the translation."""
    offenders = report.by_kind("accent")
    assert offenders == [], (
        f"{len(offenders)} accented lines outside the French catalogues:\n  " + _format(offenders)
    )


def test_no_accent_free_french_prose(report):
    """French without accents is still French, and the accent probe is blind to it."""
    offenders = report.by_kind("french")
    assert offenders == [], (
        f"{len(offenders)} lines of French prose:\n  " + _format(offenders)
    )


def test_no_french_identifier(report):
    """``taille`` is ASCII: no textual probe can see it, only an AST walk can.

    This is the gap ``test_i18n_guard.py`` leaves open — it asserts that parameter ids are
    ASCII, which a French identifier satisfies without being English.
    """
    offenders = report.by_kind("identifier")
    assert offenders == [], (
        f"{len(offenders)} French identifiers:\n  " + _format(offenders)
    )


def test_process_ids_and_choices_are_english():
    """The serialized contract, checked directly rather than through the file probes.

    A ``process_id``, a parameter id or an enumeration value is written into ``.retina``
    projects, plan JSON and recipe XML. French there would outlive the source it came from.
    """
    from retina.process.registry import all_processes, load_builtin

    load_builtin()
    stems = check_english.FRENCH_STEMS - check_english.STEM_FALSE_FRIENDS
    offenders = []
    for process_id, cls in sorted(all_processes().items()):
        for token in (process_id, *(p.id for p in cls.parameters)):
            if {part.lower() for part in token.split("_")} & stems:
                offenders.append(f"{process_id}: id {token!r}")
        for parameter in cls.parameters:
            for choice in getattr(parameter, "choices", ()) or ():
                if {part.lower() for part in str(choice).split("_")} & stems:
                    offenders.append(f"{process_id}.{parameter.id}: choice {choice!r}")

    assert offenders == [], "French in a serialized contract:\n  " + "\n  ".join(offenders)


def test_the_allowlist_stays_small():
    """An allowlist that grows without comment is a guard someone stopped believing in."""
    assert len(check_english.ALLOWED_ACCENTED) <= 15


def test_the_guard_actually_reads_the_repository(report):
    """A broken glob would make every assertion above pass by scanning nothing."""
    assert report.files_scanned > 400
