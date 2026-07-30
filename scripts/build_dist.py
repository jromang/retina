"""Packaging pre-steps: build the web frontend and the native shell, then put them in place.

Briefcase has **no pre-build hook**: anything that must exist before `briefcase create` has to
be produced by a script run by hand. That is already the case for `fetch_astap.py`; this one is
its counterpart for the two artefacts the web shell adds.

    python scripts/build_dist.py          # everything
    python scripts/build_dist.py --web    # frontend only
    python scripts/build_dist.py --shell  # native shell only

Both artefacts land **inside the Python package**, not in a separate distribution folder:

- `python/retina/resources/webui/` — Vite's output (configured in `web/vite.config.ts`),
  served by aiohttp in production and embedded in the wheel by maturin;
- `python/retina/shell/retina_shell[.exe]` — a copy of the Cargo binary, at the location
  `retina.web.find_shell()` probes first.

That is what makes the briefcase bundle trivial: `sources = ["python/retina"]` carries both of
them, with no extra packaging rule. Both paths are gitignored — they are artefacts, and the
sources live in `web/src` and `crates/retina_shell`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_SRC = ROOT / "web"
WEB_OUT = ROOT / "python" / "retina" / "resources" / "webui"
SHELL_DIR = ROOT / "python" / "retina" / "shell"
SHELL_NAME = "retina_shell.exe" if os.name == "nt" else "retina_shell"


def _configure_console() -> None:
    """The Windows console speaks cp1252: an arrow in a message would kill the script.

    Same precaution as `retina.web._configure_console` — a packaging script must not fail on
    the typography of its own traces.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _run(cmd: list[str], cwd: Path) -> None:
    printable = " ".join(cmd)
    print(f"[build] {printable}  (cwd={cwd.relative_to(ROOT)})", flush=True)
    # `shell=True` on Windows: `npm` is a `.cmd`, which CreateProcess cannot launch on its own.
    subprocess.run(cmd, cwd=cwd, check=True, shell=os.name == "nt")


def _node_modules_stale() -> bool:
    """True if the web dependencies are missing **or** predate the latest package.json.

    Testing only for the presence of `node_modules/` is not enough: when a dependency is added
    to the repository, the folder still exists but without it, and the build dies on a missing
    binary at the first line of `npm run build`. That happened with `paraglide-js` (the i18n
    toolchain). So we compare timestamps instead: `package.json` newer than
    `node_modules/.package-lock.json` means the install has to be redone.
    """
    modules = WEB_SRC / "node_modules"
    if not modules.is_dir():
        return True
    digest = modules / ".package-lock.json"  # written by npm on every install
    if not digest.is_file():
        return True
    return (WEB_SRC / "package.json").stat().st_mtime > digest.stat().st_mtime


def build_web() -> None:
    """Typecheck + Vite bundle. The typecheck is part of the build: a packaging run must not
    ship TypeScript that does not compile."""
    if _node_modules_stale():
        # `npm ci` fails when the lockfile has drifted from package.json; `install` puts it
        # back in order. We want a packaging run that completes, not one that lectures.
        _run(["npm", "install"], cwd=WEB_SRC)
    _run(["npm", "run", "build"], cwd=WEB_SRC)
    index = WEB_OUT / "index.html"
    if not index.is_file():
        raise SystemExit(f"[build] failed: {index} missing after the Vite build")
    size = sum(f.stat().st_size for f in WEB_OUT.rglob("*") if f.is_file())
    print(f"[build] frontend → {WEB_OUT.relative_to(ROOT)} ({size / 1e6:.1f} MB)", flush=True)


def build_shell() -> None:
    """Build `retina_shell` in release mode and copy it into the package."""
    _run(["cargo", "build", "--release", "-p", "retina_shell"], cwd=ROOT)
    built = ROOT / "target" / "release" / SHELL_NAME
    if not built.is_file():
        raise SystemExit(f"[build] failed: {built} not found after cargo build")
    SHELL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, SHELL_DIR / SHELL_NAME)
    size = (SHELL_DIR / SHELL_NAME).stat().st_size
    print(
        f"[build] shell → {(SHELL_DIR / SHELL_NAME).relative_to(ROOT)} ({size / 1e6:.1f} MB)",
        flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    ap = argparse.ArgumentParser(prog="build_dist", description=__doc__)
    ap.add_argument("--web", action="store_true", help="frontend only")
    ap.add_argument("--shell", action="store_true", help="native shell only")
    args = ap.parse_args(argv)

    both = not (args.web or args.shell)
    if both or args.web:
        build_web()
    if both or args.shell:
        build_shell()

    if both:
        print(
            "\n[build] ready. Remaining packaging steps:\n"
            "    python scripts/fetch_astap.py   # offline astrometric solver (Windows)\n"
            "    maturin build --release         # native core retina._core\n"
            "    briefcase create && briefcase build && briefcase package",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
