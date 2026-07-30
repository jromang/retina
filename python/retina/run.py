"""Headless execution — ``python -m retina.run recipe.py`` (no shell).

Proves console completeness: a full pipeline runs without ever importing a shell.
"""

from __future__ import annotations

import sys

from .app import app
from .process.registry import load_builtin


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    load_builtin()
    if not argv:
        print("usage: python -m retina.run <recipe.py> [args...]", file=sys.stderr)
        return 2
    recipe = argv[0]
    app.run_recipe(recipe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
