"""Burn-down meter for the French-to-English migration: how much French is left, and where.

Three probes, because no single one is sufficient:

1. **Accented characters** catch the bulk of it, but they are neither necessary nor sufficient.
   Not necessary: plenty of French prose carries no accent at all ("un worker ne touche jamais
   une WebSocket"). Not sufficient: legitimate English technical writing has accents too —
   ``à-trous``, ``Pérez``, ``moiré``, ``Hyvärinen``. Hence the allowlist, which is derived from
   the project's *existing* English content rather than guessed.
2. **French bigrams and elisions** catch the accent-free residue. Single stopwords were tried
   first and abandoned: ``la``, ``si``, ``on``, ``est``, ``note``, ``pas`` collide with English
   and with code far too often to be usable. Bigrams ("de la", "il faut", "sans quoi") and
   elisions ("d'un", "c'est", "qu'il") do not.
3. **French identifiers**, by AST walk. This one has no textual signature at all: ``taille`` is
   pure ASCII and reads as a plausible English token to every other check in the repo.

Probes 1 and 2 are aware of what kind of text they are looking at. A French string *literal* is
sometimes legitimate (a test asserting the French catalogue's output is a product test), while a
French *comment* in the same file never is. So Python files are split with ``tokenize`` and
TypeScript with a small state machine, and the string-literal exemption is granted per file
rather than per repository.

Usage::

    python scripts/check_english.py            # one summary line
    python scripts/check_english.py --list     # every offender, grouped by file
    python scripts/check_english.py --strict   # exit 1 if anything remains (for CI)
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# What is deliberately French, and stays French
# ---------------------------------------------------------------------------

#: Product catalogues. The application is bilingual by design — English by default, French
#: complete — so these files are features, not debt. Never scanned, in any probe.
CATALOGUE_PATHS = (
    "web/messages/fr.json",
    # en.json names the French language in French -- "Language: French (francais)".
    "web/messages/en.json",
    "python/retina/resources/i18n/",
)

#: Per-process user documentation is written in both languages, side by side, and so is the
#: front page: README.fr.md is the French half of a bilingual product, not untranslated debt.
CATALOGUE_SUFFIXES = ("/fr.md", "README.fr.md")

#: Files whose French *string literals* are product assertions — a test that checks the French
#: catalogue renders French must contain French. Their comments and docstrings are still checked.
STRING_LITERALS_EXEMPT = (
    "scripts/gen_process_docs.py",  # emits the French half of resources/doc/*/fr.md
    "tests/test_i18n.py",
    "tests/pipeline/test_plan.py",
    "web/e2e/",
    "web/src/shell/keybindings.ts",
)

#: Accented words that belong in English technical prose. Derived from the project's existing
#: English content (``resources/doc/*/en.md`` and ``web/messages/en.json``) rather than invented.
#: Deliberately *not* here: ``naïve``, ``résumé``, ``façade`` — English spells those without
#: accents, so leaving them out keeps the probe honest.
ALLOWED_ACCENTED = (
    "à-trous",
    "à trous",
    "Pérez",
    "moiré",
    "Hyvärinen",
    "Über",
    "längs",
    "Šidák",
    "Bézier",
    "Cauchy-Schwarz",
    # Naming French in French, the same case as en.json's "Language: French (francais)".
    "Version francaise",
    "Version fran\u00e7aise",
)

ACCENTS = re.compile(r"[éèêëàâäîïôöùûüÿçœæÉÈÊËÀÂÄÎÏÔÖÙÛÜŸÇŒÆ]")

#: Bigrams and elisions. Every entry was checked against the repo's English content for false
#: positives; "en revanche" and "au lieu" survive because no English sentence contains them.
FRENCH_BIGRAMS = re.compile(
    r"(?<![\w-])(?:"
    r"de la|de l'|à la|à l'|d'un|d'une|c'est|n'est|n'a |n'y |qu'il|qu'elle|qu'on|qu'un|"
    r"s'il|s'y |l'on|jusqu'|lorsqu'|puisqu'|"
    # `on a ` and `on y ` were dropped: they fire on ordinary English -- "on a dark
    # background", "works on a copy" -- and cost more in false positives than they catch.
    r"qui ne|qui est|ce qui|ce que|ce n'|il faut|il y a|on ne|"
    r"dans le|dans la|dans les|pour le|pour la|pour les|sur le|sur la|sur les|"
    r"par le|par la|par les|avec le|avec la|avec les|sans le|sans la|"
    r"est un|est une|est le|est la|sont des|sont les|"
    r"ne pas|ne fait|ne sert|plus de|moins de|au lieu|à partir|"
    r"c'est-à-dire|autrement dit|en revanche|d'où|donc le|donc la|sans quoi|faute de|"
    r"plutôt que|alors que|tandis que|parce que|bien que|afin de|afin que|"
    r"il suffit|il reste|il manque|elle est|elles sont|ils sont"
    r")(?![\w-])",
    re.IGNORECASE,
)

#: French identifier stems, from the census. Matched against ``_``-split identifier parts, so
#: ``chemin_sortie`` is caught by two entries and ``patheme`` by none.
#: A split block rather than a list literal: a hundred one-word entries as ``"x",`` lines would
#: be four times as long and no easier to scan or amend. Hence the ``noqa``.
FRENCH_STEMS = frozenset(
    """
    chemin chemins sortie sorties entree entrees cible cibles inventaire inventaires
    fichier fichiers dossier dossiers racine racines fenetre fenetres vue vues
    valeur valeurs cle cles etape etapes taille tailles ligne lignes colonne colonnes
    resultat resultats largeur hauteur profondeur etoile etoiles ciel etat etats
    donnee donnees texte textes attendu attendus obtenu obtenus masque masques
    catalogue catalogues canal canaux motif motifs seuil seuils poids bruit bruits
    echelle echelles courant courante gauche droite haut bas debut fin
    liste listes tableau tableaux ecart ecarts premier dernier suivant precedent
    nom noms nombre compteur parseur coupable coupables vide vides plein
    essai essais brute brutes brutes_mono brutes_osc brutes_framing faux fausse
    verifier charger enregistrer ouvrir fermer creer supprimer ajouter retirer
    calculer appliquer executer lancer arreter attendre chercher trouver
    manquant manquante manquantes divergent divergente divergentes flou floue floues
    domaine domaines interieur exterieur arbre feuille noeud
    numero contenu contenus correspondance correspondances marqueur marqueurs
    sauvegarde reglage reglages apercu apercus rendu couche couches
    """.split()  # noqa: SIM905
)

#: Identifier parts that look French but are not, or are identical in both languages.
STEM_FALSE_FRIENDS = frozenset(
    """
    fin point points zone note nom_de format image table type mode argument
    catalogue catalogues
    """.split()  # noqa: SIM905
)

SCANNED_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".css", ".html", ".toml", ".cfg",
    ".json", ".md", ".yml", ".yaml", ".sh", ".fish", ".txt",
}

#: Generated, vendored or lock content — never authored here, never worth reporting. This file
#: is on the list because it is the meter: it necessarily holds specimens of what it looks for,
#: and counting them would make the burn-down number lie by a constant.
SKIP_PATHS = (
    "web/src/paraglide/", "node_modules/", "target/", ".venv/",
    "Cargo.lock", "package-lock.json",
    "python/retina/resources/licenses/",
    "scripts/check_english.py",
)


@dataclass
class Offender:
    path: str
    line: int
    kind: str  # "accent" | "french" | "identifier"
    where: str  # "comment" | "docstring" | "string" | "text" | "code"
    excerpt: str


@dataclass
class Report:
    offenders: list[Offender] = field(default_factory=list)
    files_scanned: int = 0

    def add(self, *args, **kwargs) -> None:
        self.offenders.append(Offender(*args, **kwargs))

    def by_kind(self, kind: str) -> list[Offender]:
        return [o for o in self.offenders if o.kind == kind]

    def files_touched(self) -> set[str]:
        return {o.path for o in self.offenders}


# ---------------------------------------------------------------------------
# Text classification
# ---------------------------------------------------------------------------


def relative(path: Path) -> str:
    """Repository-relative path with forward slashes, on every platform.

    `Path.relative_to` yields backslashes on Windows, so `rel.startswith("web/e2e/")` silently
    stopped matching there -- and the e2e specs, whose French assertions are a product test,
    were reported as offenders. The exemption lists are written with `/`; this is what makes
    them mean the same thing on both platforms.
    """
    return path.relative_to(ROOT).as_posix()


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    paths = []
    for rel in out.splitlines():
        if any(rel.startswith(p) or p in rel for p in SKIP_PATHS):
            continue
        if any(rel.startswith(p) for p in CATALOGUE_PATHS):
            continue
        if any(rel.endswith(s) for s in CATALOGUE_SUFFIXES):
            continue
        path = ROOT / rel
        if path.suffix in SCANNED_SUFFIXES and path.is_file():
            paths.append(path)
    return paths


def strings_are_exempt(rel: str) -> bool:
    return any(rel.startswith(p) or rel == p for p in STRING_LITERALS_EXEMPT)


def split_python(source: str) -> list[tuple[int, str, str]]:
    """Yield ``(line, kind, text)`` for a Python file, kind in comment/docstring/string.

    ``tokenize`` rather than a regex because a ``#`` inside a string literal, and a triple quote
    inside a comment, both defeat the regex — and both occur in this repository.
    """
    chunks: list[tuple[int, str, str]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return [(i, "text", line) for i, line in enumerate(source.splitlines(), 1)]

    # A STRING token is a docstring when it is the first statement of a module, class or
    # function — approximated by "preceded only by NEWLINE/INDENT/DEDENT/COMMENT/NL".
    prev_meaningful: int | None = None
    for index, tok in enumerate(tokens):
        if tok.type == tokenize.COMMENT:
            chunks.append((tok.start[0], "comment", tok.string))
        elif tok.type == tokenize.STRING:
            kind = "string"
            if prev_meaningful is None or tokens[prev_meaningful].type in (
                tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
                tokenize.ENCODING,
            ):
                kind = "docstring"
            chunks.append((tok.start[0], kind, tok.string))
        if tok.type not in (
            tokenize.NL, tokenize.COMMENT, tokenize.ENCODING, tokenize.ENDMARKER
        ):
            prev_meaningful = index
    return chunks


def split_curly(source: str) -> list[tuple[int, str, str]]:
    """Yield ``(line, kind, text)`` for C-like syntax (TS, TSX, Rust, CSS).

    A hand-rolled scanner rather than a regex, for the same reason as the Python case: the repo
    contains ``//`` inside string literals and quotes inside comments. Template literals are
    treated as strings; the expressions they interpolate are not separated out, which is
    deliberate — a French comment inside a ``${}`` is vanishingly rare and would be caught by
    the identifier probe anyway.
    """
    chunks: list[tuple[int, str, str]] = []
    i, line, n = 0, 1, len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if ch == "\n":
            line += 1
            i += 1
        elif ch == "/" and nxt == "/":
            end = source.find("\n", i)
            end = n if end == -1 else end
            chunks.append((line, "comment", source[i:end]))
            i = end
        elif ch == "/" and nxt == "*":
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            text = source[i:end]
            chunks.append((line, "comment", text))
            line += text.count("\n")
            i = end
        elif ch in "\"'`":
            quote, j = ch, i + 1
            while j < n:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == quote:
                    break
                if source[j] == "\n" and quote != "`":
                    break
                j += 1
            text = source[i : j + 1]
            chunks.append((line, "string", text))
            line += text.count("\n")
            i = j + 1
        else:
            i += 1
    return chunks


def strip_allowed(text: str) -> str:
    for word in ALLOWED_ACCENTED:
        text = text.replace(word, "")
    return text


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def probe_text(path: Path, report: Report) -> None:
    rel = relative(path)
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    report.files_scanned += 1

    if path.suffix == ".py":
        chunks = split_python(source)
    elif path.suffix in (".ts", ".tsx", ".js", ".jsx", ".rs", ".css"):
        chunks = split_curly(source)
    else:
        chunks = [(i, "text", ln) for i, ln in enumerate(source.splitlines(), 1)]

    exempt = strings_are_exempt(rel)
    for lineno, kind, text in chunks:
        if kind == "string" and exempt:
            continue
        probe = strip_allowed(text)
        excerpt = " ".join(text.split())[:90]
        if ACCENTS.search(probe):
            report.add(rel, lineno, "accent", kind, excerpt)
        elif FRENCH_BIGRAMS.search(probe):
            report.add(rel, lineno, "french", kind, excerpt)


def probe_identifiers(path: Path, report: Report) -> None:
    """Walk the AST for French identifiers — the probe with no textual signature."""
    rel = relative(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return

    def check(name: str, lineno: int, what: str) -> None:
        parts = {p.lower() for p in name.split("_") if p}
        hits = (parts & FRENCH_STEMS) - STEM_FALSE_FRIENDS
        if hits:
            report.add(rel, lineno, "identifier", what, f"{name}  ({', '.join(sorted(hits))})")

    seen: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            key = (node.id, node.lineno)
            if key not in seen:
                seen.add(key)
                check(node.id, node.lineno, "name")
        elif isinstance(node, ast.arg):
            check(node.arg, node.lineno, "arg")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            check(node.name, node.lineno, "def")
        elif isinstance(node, ast.ClassDef):
            check(node.name, node.lineno, "class")
        elif isinstance(node, ast.keyword) and node.arg:
            check(node.arg, node.value.lineno, "kwarg")
        elif isinstance(node, ast.Attribute):
            check(node.attr, node.lineno, "attr")


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print every offender")
    parser.add_argument("--kind", choices=("accent", "french", "identifier"), help="filter")
    parser.add_argument("--path", help="only files whose path contains this substring")
    parser.add_argument("--strict", action="store_true", help="exit 1 if anything remains")
    args = parser.parse_args()

    report = Report()
    for path in tracked_files():
        rel = relative(path)
        if args.path and args.path not in rel:
            continue
        probe_text(path, report)
        if path.suffix == ".py":
            probe_identifiers(path, report)

    accents = report.by_kind("accent")
    french = report.by_kind("french")
    identifiers = report.by_kind("identifier")

    if args.list:
        grouped: dict[str, list[Offender]] = defaultdict(list)
        for off in report.offenders:
            if args.kind and off.kind != args.kind:
                continue
            grouped[off.path].append(off)
        for path in sorted(grouped):
            print(f"\n{path}")
            for off in sorted(grouped[path], key=lambda o: o.line):
                print(f"  {off.line:>5}  {off.kind:<10} {off.where:<9} {off.excerpt}")
        print()

    print(
        f"remaining: {len(accents)} accented, {len(french)} french-prose, "
        f"{len(identifiers)} identifiers "
        f"— across {len(report.files_touched())} of {report.files_scanned} files"
    )
    if args.strict and report.offenders:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
