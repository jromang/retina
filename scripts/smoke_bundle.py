"""Exercise a packaged bundle with *its own* interpreter, before the installer is built.

"The application launches" proves nothing here. The processes import scipy, scikit-image and
photutils **lazily**, inside their method bodies, so a bundle missing those wheels starts
normally, lists all 141 processes, and dies with a ``ModuleNotFoundError`` on the first click.
That failure is invisible to any check that only opens the window.

So this script does three things, in order of how much they catch:

1. **Derives** the lazy-import list from the packaged source by walking its AST, then imports
   every one of them. Deriving rather than listing is the whole point: adding a dependency to a
   process without adding it to the briefcase ``requires`` fails CI automatically, which turns
   the packaging invariant from a paragraph into a machine check.
2. Imports every ``retina.processes`` module, because the entry-point registry never mentions a
   module nothing references.
3. Runs a real miniature pipeline — one process per family — plus a FITS round trip and a
   raster export, and checks that ``retina._core`` is the native extension rather than the
   numpy fallback.

It runs **under the bundle's Python**, not the runner's, which is what makes it meaningful.
Two details make that work:

- the embedded distribution ships a ``python3xx._pth``, and the presence of that file makes
  CPython **ignore ``PYTHONPATH``** — so the paths are inserted into ``sys.path`` from inside;
- the interpreter is discovered rather than hardcoded, because the layout differs between
  briefcase templates.

Usage::

    python scripts/smoke_bundle.py --tree build/retina/windows/app
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

# Lazily imported names that are NOT expected in the bundle, each for a stated reason. Anything
# absent from this set and missing at runtime is a packaging bug, which is the point.
IGNORED_ROOTS = {
    "retina", "__future__",
    # Optional GPU acceleration: the CuPy wheel is tied to a CUDA branch, and every ported
    # process falls back on the CPU path when it is absent.
    "cupy", "cupyx",
    # Does not build under MSVC; ASTAP is the offline plate-solver on Windows. The Linux and
    # macOS briefcase sections reintroduce it.
    "astrometry",
    # Transitive through IPython, imported defensively.
    "traitlets",
}
# The standard library needs no checking and would only add noise.
IGNORED_ROOTS |= set(sys.stdlib_module_names)


def find_runtime(tree: Path) -> tuple[Path, Path, Path]:
    """Locate ``(interpreter, app_dir, app_packages_dir)`` inside a briefcase build tree."""
    candidates = list(tree.rglob("python.exe")) + list(tree.rglob("bin/python3"))
    if not candidates:
        raise SystemExit(f"no bundled interpreter under {tree}")
    interpreter = candidates[0]
    src = interpreter.parent
    app = next((p for p in (src / "app", tree / "app") if p.is_dir()), None)
    packages = next((p for p in (src / "app_packages", tree / "app_packages") if p.is_dir()), None)
    if app is None or packages is None:
        raise SystemExit(f"app/ or app_packages/ not found under {src}")
    return interpreter, app, packages


def lazy_imports(package_root: Path) -> set[str]:
    """Top-level module names imported from *inside* a function or method body.

    A module-level import would fail at startup and be caught by anything; a lazy one waits
    for the user to click. Only the latter is interesting here.
    """
    found: set[str] = set()
    for path in sorted(package_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Import):
                    found.update(alias.name.split(".")[0] for alias in inner.names)
                elif isinstance(inner, ast.ImportFrom) and inner.level == 0 and inner.module:
                    found.add(inner.module.split(".")[0])
    return {name for name in found if name not in IGNORED_ROOTS}


def run_inside(app: Path, packages: Path) -> int:
    """The part that executes under the bundle's interpreter."""
    sys.path.insert(0, str(packages))
    sys.path.insert(0, str(app))

    failures: list[str] = []

    # --- 1. every lazy import, reporting the whole list rather than the first failure -------
    names = sorted(lazy_imports(app / "retina"))
    print(f"[smoke] {len(names)} lazily imported modules derived from the bundled source")
    for name in names:
        try:
            __import__(name)
        except Exception as exc:
            failures.append(f"lazy import {name}: {type(exc).__name__}: {exc}")

    # --- 2. every process module, including those nothing references -------------------------
    import importlib

    from retina.process.registry import all_processes, load_builtin

    for path in sorted((app / "retina" / "processes").glob("*.py")):
        if path.stem == "__init__":
            continue
        try:
            importlib.import_module(f"retina.processes.{path.stem}")
        except Exception as exc:
            failures.append(f"process module {path.stem}: {type(exc).__name__}: {exc}")

    load_builtin()
    registered = all_processes()
    print(f"[smoke] {len(registered)} processes registered")
    if len(registered) < 100:
        failures.append(f"only {len(registered)} processes registered; the catalog is truncated")

    # --- 3. a real miniature pipeline, one process per family --------------------------------
    import numpy as np
    from retina.model.image import Image

    rng = np.random.default_rng(0)
    data = rng.random((64, 64, 3), dtype=np.float32) * 0.1
    data[30:34, 30:34, :] += 0.8  # something star-like to find

    exercises = [
        ("GaussianConvolution", {"sigma": 1.5}),          # Rust core
        ("HistogramTransformation", {"midtones": 0.4}),   # numpy
        ("Statistics", {}),                               # astropy
        ("BackgroundExtraction", {}),                     # photutils
        ("NoiseReduction", {}),                           # scipy / skimage
        ("WaveletDenoise", {}),                           # PyWavelets
        ("FastNLMeansDenoise", {}),                       # OpenCV
        ("ComponentSeparation", {}),                      # scikit-learn
    ]
    for process_id, values in exercises:
        cls = registered.get(process_id)
        if cls is None:
            failures.append(f"process {process_id} is not registered")
            continue
        try:
            # execute_on_image, not execute_on: the latter wants a View and its history
            # bracket, and a bundle check has no window.
            cls(**values).execute_on_image(Image(data.copy()))
        except Exception as exc:
            failures.append(f"{process_id}: {type(exc).__name__}: {exc}")
        else:
            print(f"[smoke] {process_id} ok")

    # --- 4. formats, the native core, and the French catalog ---------------------------------
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        try:
            from retina.io.fits import load_fits, save_fits

            path = str(Path(tmp) / "roundtrip.fits")
            save_fits(path, Image(data.copy()), {})
            reloaded, _ = load_fits(path)
            assert reloaded.width == 64, "FITS round trip changed the geometry"
            print("[smoke] FITS round trip ok")
        except Exception as exc:
            failures.append(f"FITS round trip: {type(exc).__name__}: {exc}")

        try:
            from retina.io.raster import save_raster

            save_raster(str(Path(tmp) / "export.tif"), Image(data.copy()))
            save_raster(str(Path(tmp) / "export.png"), Image(data.copy()))
            print("[smoke] TIFF and PNG export ok")
        except Exception as exc:
            failures.append(f"raster export: {type(exc).__name__}: {exc}")

    try:
        from retina import _core

        assert hasattr(_core, "__file__"), "retina._core is not the compiled extension"
        print(f"[smoke] native core ok: {_core.__file__}")
    except Exception as exc:
        failures.append(f"native core: {type(exc).__name__}: {exc}")

    try:
        from retina import i18n

        assert i18n.translate("Deconvolution", "fr") != "Deconvolution", (
            "the French catalog did not load - the .mo is missing from the bundle"
        )
        print("[smoke] French catalog ok")
    except Exception as exc:
        failures.append(f"French catalog: {type(exc).__name__}: {exc}")

    if failures:
        print(f"\n[smoke] {len(failures)} FAILURES:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\n[smoke] bundle is complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tree", required=True,
                        help="briefcase build tree, e.g. build/retina/windows/app")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--app", help=argparse.SUPPRESS)
    parser.add_argument("--packages", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.inside:
        return run_inside(Path(args.app), Path(args.packages))

    interpreter, app, packages = find_runtime(Path(args.tree))
    print(f"[smoke] interpreter : {interpreter}")
    print(f"[smoke] app         : {app}")
    print(f"[smoke] app_packages: {packages}")
    return subprocess.run(
        [str(interpreter), str(Path(__file__).resolve()), "--tree", args.tree,
         "--inside", "--app", str(app), "--packages", str(packages)],
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
