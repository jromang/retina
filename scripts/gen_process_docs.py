#!/usr/bin/env python
"""Generate the documentation **stubs** for the processes (FR + EN).

For every registered process without a ``<lang>.md`` file, write a skeleton: frontmatter (id,
category, title, brief taken from the docstring, resolved icon, empty keywords/related) + the
template sections with ``TODO`` markers, and a *Parameters* section **auto-filled** from the
schema (id, type, default, range, tooltip/label).

**Idempotent**: never rewrites an existing file (hand-written prose wins).

    python scripts/gen_process_docs.py            # create the missing ones
    python scripts/gen_process_docs.py --list     # list what is missing, without writing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import retina
from retina import documentation as D

# Section headings per language (the generic template, spelled out everywhere).
SECTIONS = {
    "fr": ["Résumé", "Cas d'usage", "Fonctionnement", "Mathématiques",
           "Paramètres", "Astuces & pièges", "Voir aussi", "Références"],
    "en": ["Summary", "Use cases", "How it works", "Mathematics",
           "Parameters", "Tips & pitfalls", "See also", "References"],
}
TODO = {"fr": "_À rédiger (TODO)._", "en": "_To be written (TODO)._"}
NO_PARAMS = {"fr": "_Ce process n'a pas de paramètre._",
             "en": "_This process has no parameter._"}
NO_MATH = {"fr": "_Sans objet pour ce process._", "en": "_Not applicable._"}


def _brief(cls) -> str:
    doc = (cls.__doc__ or "").strip()
    if not doc:
        return ""
    first = doc.splitlines()[0].strip()
    return first.replace('"', "'")


def _params_md(cls, lang: str) -> str:
    if not cls.parameters:
        return NO_PARAMS[lang]
    lines = []
    for p in cls.parameters:
        rng = ""
        if p.min is not None or p.max is not None:
            lo = "" if p.min is None else f"{p.min:g}"
            hi = "" if p.max is None else f"{p.max:g}"
            rng = f", {'plage' if lang == 'fr' else 'range'} `{lo}`–`{hi}`"
        choices = ""
        if p.choices:
            joined = ', '.join(f'`{c}`' for c in p.choices)
            choices = f", {'choix' if lang == 'fr' else 'choices'}: {joined}"
        default = "" if lang == "fr" else "default"
        default = ("défaut" if lang == "fr" else "default")
        desc = (p.tooltip or p.label or "").strip()
        lines.append(
            f"- **`{p.id}`** — *{p.type}*, {default} `{p.default}`{rng}{choices}."
            + (f" {desc}" if desc else "")
        )
    return "\n".join(lines)


def _front(cls, lang: str) -> str:
    icon = D.icon_name(cls.process_id)
    title = cls.process_id
    brief = _brief(cls) if lang == "fr" else ""
    return (
        "---\n"
        f"id: {cls.process_id}\n"
        f"category: {cls.category}\n"
        f"title: {title}\n"
        f'brief: "{brief}"\n'
        "keywords: []\n"
        "related: []\n"
        f"icon: {icon}\n"
        "references: []\n"
        "---\n"
    )


def _body(cls, lang: str) -> str:
    out = []
    for sec in SECTIONS[lang]:
        out.append(f"\n## {sec}\n")
        if sec in ("Paramètres", "Parameters"):
            out.append(_params_md(cls, lang))
        elif sec in ("Mathématiques", "Mathematics"):
            out.append(NO_MATH[lang])
        elif sec in ("Voir aussi", "See also", "Références", "References"):
            out.append("")
        else:
            out.append(TODO[lang])
    return "\n".join(out).strip() + "\n"


def generate(list_only: bool = False) -> int:
    created = 0
    for pid, cls in sorted(retina.all_processes().items()):
        d = D.doc_dir(pid)
        for lang in ("fr", "en"):
            path = d / f"{lang}.md"
            if path.exists():
                continue
            if list_only:
                print("manquant:", path.relative_to(D._DOC.parent.parent))
                created += 1
                continue
            d.mkdir(parents=True, exist_ok=True)
            path.write_text(_front(cls, lang) + _body(cls, lang), encoding="utf-8")
            created += 1
    verb = "à créer" if list_only else "créés"
    print(f"{created} fichier(s) {verb}.")
    return created


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="liste les manquants sans écrire")
    args = ap.parse_args()
    generate(list_only=args.list)
