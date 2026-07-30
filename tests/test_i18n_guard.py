"""Guard rail: no interface string may escape the catalogue.

Same spirit as ``web/tests/menus.test.ts`` — an architectural invariant entrusted to a test
rather than to code review. Three things are checked, and each one corresponds to a real
possible regression:

1. **a parameter label written without ``N_``** would never be extracted, hence never
   translated; it would show up in English inside a French interface with nothing to flag it;
2. **an accented msgid** betrays French text left in the code: msgids are the English version,
   that is the project's gettext convention and what makes a third-party process readable
   without a catalogue;
3. **an incomplete catalogue or a stale ``.mo``** would make the application speak English
   silently — ``gettext`` is loaded with ``fallback=True``, so nothing raises, and the failure
   only shows on screen.

Failure messages name the culprits: an expected empty list beats a boolean.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROCESSES = ROOT / "python" / "retina" / "processes"
I18N = ROOT / "python" / "retina" / "resources" / "i18n"
PO = I18N / "fr" / "LC_MESSAGES" / "retina.po"
MO = I18N / "fr" / "LC_MESSAGES" / "retina.mo"

#: `label=` / `tooltip=` followed by whatever comes right after — literal or call.
ARGUMENT = re.compile(r"\b(label|tooltip)\s*=\s*(?P<value>N_\(|f?['\"])")

#: The accented letters of French, spelled as escapes rather than as themselves. They are data
#: here, not prose, and ``scripts/check_english.py`` — which measures how much French is left in
#: the repository — cannot tell the difference. Escapes keep this file out of its count without
#: weakening the check: the code points are e/a/u/o/i/c with the French diacritics, plus the
#: oe ligature, in both cases.
ACCENTS = re.compile(
    "["
    "\u00e9\u00e8\u00ea\u00eb\u00e0\u00e2\u00e4"  # e a with acute, grave, circumflex, diaeresis
    "\u00f9\u00fb\u00fc\u00f4\u00f6\u00ee\u00ef\u00e7\u0153"  # u o i, cedilla, oe
    "\u00c9\u00c8\u00ca\u00cb\u00c0\u00c2\u00c4"  # the same, uppercase
    "\u00d9\u00db\u00dc\u00d4\u00d6\u00ce\u00cf\u00c7\u0152"
    "]"
)


def _process_files() -> list[Path]:
    return sorted(p for p in PROCESSES.glob("*.py") if p.name != "__init__.py")


def test_every_parameter_label_goes_through_the_marker():
    """A bare ``label="…"`` enters no catalogue — and nobody notices."""
    offenders: list[str] = []
    for file in _process_files():
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            for match in ARGUMENT.finditer(line):
                if not match.group("value").startswith("N_("):
                    offenders.append(f"{file.relative_to(ROOT)}:{number}: {line.strip()}")

    assert offenders == [], (
        "unmarked parameter labels (expected `label=N_(\"…\")`):\n  "
        + "\n  ".join(offenders)
    )


def test_msgids_are_in_english():
    """An accent in a msgid is French left in the source code."""
    marker = re.compile(r"""(?:N_|_t)\(\s*(['"])(?P<text>(?:(?!\1).)*)\1""")
    offenders: list[str] = []
    for file in sorted((ROOT / "python" / "retina").rglob("*.py")):
        content = file.read_text(encoding="utf-8")
        for match in marker.finditer(content):
            text = match.group("text")
            if ACCENTS.search(text):
                offenders.append(f"{file.relative_to(ROOT)}: {text[:70]!r}")

    assert offenders == [], (
        "non-English msgid — msgids are the reference version:\n  "
        + "\n  ".join(offenders)
    )


#: Root of the domain: **all** of ``python/retina/``, whose exceptions reach the user (relayed
#: as-is by ``rpc.py`` all the way to the toasts, and read verbatim in the console).
DOMAIN = ROOT / "python" / "retina"

#: What the rule does not cover. ``server/`` is excluded from it: its ``RpcError`` carry their
#: own conventions — an error code and a message already meant for the transport — and do not
#: go through ``str(exc)`` the way domain exceptions do. ``resources/`` holds no application
#: code (docs, icons, catalogues, Vite build).
OUT_OF_DOMAIN = ("server", "resources")


def _literal_fragments(node: ast.expr):
    """The literal string fragments of an exception argument (constant, f-string, +)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node
    elif isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                yield value
    elif isinstance(node, ast.BinOp):
        yield from _literal_fragments(node.left)
        yield from _literal_fragments(node.right)


def _is_marked(node: ast.expr) -> bool:
    """True if the argument goes through ``_t`` — directly or via ``_t("…").format(…)``."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_t":
        return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        return _is_marked(node.func.value)
    return False


def test_domain_exception_messages_are_marked():
    """A bare ``raise ValueError("…")`` from the domain lands in a toast as-is, never translated.

    The relay is ``server/rpc.py`` (``f"{type(exc).__name__}: {exc}"``): what the domain raises
    is what the user reads. Hence the rule: every literal message of a domain exception goes
    through ``_t(…)`` — English msgid, French in the catalogue. f-strings are doubly forbidden:
    Babel does not extract them, even under ``_t``.

    The analysis is syntactic (AST) and covers concatenations; a message built without a
    literal (variable, ``str(exc)``) is none of this test's business.

    The rule covers **all** of ``python/retina/`` except ``server/`` (cf.
    :data:`OUT_OF_DOMAIN`): the shell raises ``RpcError``, which are a transport contract
    (code + message) and not a domain exception relayed as-is.
    """
    offenders: list[str] = []
    for file in sorted(DOMAIN.rglob("*.py")):
        relative = file.relative_to(DOMAIN)
        if relative.parts[0] in OUT_OF_DOMAIN:
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            exc = node.exc
            if not isinstance(exc, ast.Call) or not exc.args:
                continue
            argument = exc.args[0]
            if _is_marked(argument):
                # The msgid must stay a constant: an f-string under _t is never
                # extracted and the English-msgid test would not see it.
                inside = argument
                while (
                    isinstance(inside, ast.Call)
                    and isinstance(inside.func, ast.Attribute)
                    and inside.func.attr == "format"
                ):
                    inside = inside.func.value
                if isinstance(inside, ast.Call) and inside.args and isinstance(
                    inside.args[0], ast.Constant
                ):
                    continue
            if not list(_literal_fragments(argument)):
                continue
            line = getattr(argument, "lineno", node.lineno)
            offenders.append(f"{file.relative_to(ROOT)}:{line}")

    assert offenders == [], (
        "domain exception messages outside the catalogue — expected "
        '`raise XError(_t("English message"))` or `_t("… {x}").format(x=…)`:\n  '
        + "\n  ".join(offenders)
    )


def test_the_french_catalogue_is_complete():
    """An untranslated string shows up in English, with no warning."""
    babel = pytest.importorskip("babel.messages.pofile", reason="extra [dev] missing")

    assert PO.is_file(), f"catalogue missing: {PO.relative_to(ROOT)} — run " \
                         "python scripts/update_translations.py"
    with PO.open(encoding="utf-8") as fh:
        catalog = babel.read_po(fh, locale="fr")

    empty_items = [m.id for m in catalog if m.id and not m.string]
    blurred_items = [m.id for m in catalog if m.id and m.fuzzy]

    assert empty_items == [], ("strings with no French translation:\n  "
                               + "\n  ".join(map(repr, empty_items)))
    assert blurred_items == [], ("fuzzy translations to review:\n  "
                                 + "\n  ".join(map(repr, blurred_items)))


def test_the_compiled_catalogue_is_up_to_date():
    """The ``.mo`` is versioned: stale, it freezes the translation at an earlier state.

    Comparison by **content**, not by dates: a ``git checkout`` gives arbitrary mtimes, and a
    test that depended on them would fail at the mercy of clones.
    """
    pofile = pytest.importorskip("babel.messages.pofile", reason="extra [dev] missing")
    mofile = pytest.importorskip("babel.messages.mofile", reason="extra [dev] missing")

    assert MO.is_file(), f"compiled catalogue missing: {MO.relative_to(ROOT)}"
    with PO.open(encoding="utf-8") as fh:
        babel_source = pofile.read_po(fh, locale="fr")
    with MO.open("rb") as fh:
        compile_ = mofile.read_mo(fh)

    expected = {m.id: m.string for m in babel_source if m.id and m.string}
    actual = {m.id: m.string for m in compile_ if m.id}
    missing_items = sorted(set(expected) - set(actual))
    diverging = sorted(k for k in set(expected) & set(actual) if expected[k] != actual[k])

    assert missing_items == [], (
        f"{len(missing_items)} translated strings missing from the .mo — recompile with "
        "python scripts/update_translations.py:\n  " + "\n  ".join(map(repr, missing_items[:20]))
    )
    assert diverging == [], (
        ".mo diverges from the .po:\n  " + "\n  ".join(map(repr, diverging[:20]))
    )


def test_translated_labels_do_not_change_parameter_ids():
    """Ids are the serialisation key: translating them would break every project.

    This test is what makes the invariant explicit — the temptation, while translating, is to
    "modernise" the identifier along the way.
    """
    from retina.process.registry import all_processes, load_builtin

    load_builtin()
    offenders = [
        f"{cls.process_id}.{param.id}"
        for cls in all_processes().values()
        for param in cls.parameters
        if ACCENTS.search(param.id) or not param.id.isascii()
    ]
    assert offenders == [], "non-ASCII parameter ids:\n  " + "\n  ".join(offenders)
