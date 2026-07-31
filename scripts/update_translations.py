#!/usr/bin/env python3
"""Extract, update and compile the Python translation catalogs.

A **deliberate** act, like ``gen_icons.py`` or ``gen_web_fixtures.py``: nothing runs it
automatically. It produces three things, in this order:

1. ``python/retina/resources/i18n/retina.pot`` — the template, rebuilt on every pass;
2. ``python/retina/resources/i18n/<lang>/LC_MESSAGES/retina.po`` — merged with the existing
   one, so **no translation is ever lost**: strings that disappeared become obsolete and new
   ones arrive empty;
3. the ``.mo`` compiled next to the ``.po``.

The ``.mo`` is **versioned**, contrary to the usual practice of compiling at packaging time.
That is deliberate: ``retina`` installs as a wheel through maturin, which copies
``resources/**`` verbatim and has no compilation hook. A missing ``.mo`` would break nothing —
``gettext`` is loaded with ``fallback=True``, and the application would speak English — but it
would do so *silently*, which is exactly the kind of regression one only notices after a
release. Hence the ``tests/test_i18n_guard.py`` safety net.

The **frontend has its own toolchain** (Paraglide, ``cd web && npm run messages``): this script
does not touch it.

Usage:
    python scripts/update_translations.py            # extract, merge, compile
    python scripts/update_translations.py --check    # rewrites nothing, says what is missing
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _console import configure as _configure_console

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "python" / "retina" / "resources" / "i18n"
POT = I18N / "retina.pot"
DOMAIN = "retina"

#: Languages to maintain. English is not one of them: it is the language of the msgids.
LOCALES = ("fr",)


def _run(args: list[str]) -> None:
    printable = " ".join(args)
    print(f"[i18n] {printable}", flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def _po(locale: str) -> Path:
    return I18N / locale / "LC_MESSAGES" / f"{DOMAIN}.po"


def extract() -> None:
    POT.parent.mkdir(parents=True, exist_ok=True)
    _run([
        sys.executable, "-m", "babel.messages.frontend", "extract",
        "-F", "babel.cfg",
        # `_` is deliberately absent: it serves as a throwaway variable across the repository.
        "-k", "_t", "-k", "N_",
        "--project", "Retina",
        "--copyright-holder", "Retina",
        "--no-location",  # otherwise every line move rewrites the whole .po
        "-o", str(POT.relative_to(ROOT)),
        "python/retina",
    ])


def update() -> None:
    for locale in LOCALES:
        target = _po(locale)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            _run([sys.executable, "-m", "babel.messages.frontend", "update",
                  "-i", str(POT.relative_to(ROOT)), "-l", locale,
                  "-d", str(I18N.relative_to(ROOT)), "-D", DOMAIN,
                  "--previous"])
        else:
            _run([sys.executable, "-m", "babel.messages.frontend", "init",
                  "-i", str(POT.relative_to(ROOT)), "-l", locale,
                  "-d", str(I18N.relative_to(ROOT)), "-D", DOMAIN])


def compile_catalogs(strict: bool = False) -> None:
    for locale in LOCALES:
        args = [sys.executable, "-m", "babel.messages.frontend", "compile",
                "-d", str(I18N.relative_to(ROOT)), "-D", DOMAIN, "-l", locale,
                "--statistics"]
        if strict:
            args.append("--use-fuzzy")
        _run(args)


def check() -> int:
    """Return a non-zero exit code if any string is still untranslated."""
    from babel.messages.pofile import read_po

    missing_items = 0
    for locale in LOCALES:
        path = _po(locale)
        if not path.exists():
            print(f"[i18n] {locale}: catalog missing — run this script without --check")
            return 1
        with path.open(encoding="utf-8") as fh:
            catalog = read_po(fh)
        empty_items = [msg.id for msg in catalog if msg.id and not msg.string]
        fuzzy_items = [msg.id for msg in catalog if msg.id and msg.fuzzy]
        print(f"[i18n] {locale}: {len(catalog)} strings, "
              f"{len(empty_items)} untranslated, {len(fuzzy_items)} fuzzy")
        for msgid in empty_items[:20]:
            print(f"    ✗ {msgid!r}")
        missing_items += len(empty_items)
    return 1 if missing_items else 0


def main() -> int:
    _configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="writes nothing; exits with an error if strings remain untranslated")
    args = parser.parse_args()

    try:
        import babel  # noqa: F401
    except ImportError:
        print("[i18n] Babel missing — pip install -e '.[dev]'", file=sys.stderr)
        return 2

    if args.check:
        return check()

    extract()
    update()
    compile_catalogs()
    print(f"[i18n] catalogs up to date in {I18N.relative_to(ROOT)}")
    print("[i18n] translate the empty msgstr entries, then run again to recompile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
