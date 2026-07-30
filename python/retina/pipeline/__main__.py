"""Pre-processing CLI: ``python -m retina.pipeline <folder>``.

The complete pipeline **without the shell** — this is the test of the "headless first" rule:
if this command builds the masters and the integrated images on a machine without a display,
then the GUI really is just one more client.

    python -m retina.pipeline /data/M31
    python -m retina.pipeline /data/M31 --preset mono_sho --plan-only
    python -m retina.pipeline /data/M31 --out /scratch/m31 --force
"""

from __future__ import annotations

import argparse
import sys

from ..process.registry import load_builtin
from .plan import plan as build_plan
from .presets import PRESETS
from .runner import run as run_plan
from .scan import scan


def _bar(fraction: float | None, message: str) -> None:
    """One-line progress bar — rewritten in place, silent if redirected."""
    if not sys.stderr.isatty():
        return
    if fraction is None:
        sys.stderr.write(f"\r  … {message[:70]:<70}")
    else:
        filled = int(round(fraction * 30))
        sys.stderr.write(f"\r  [{'#' * filled}{'·' * (30 - filled)}] "
                         f"{fraction * 100:3.0f}% {message[:45]:<45}")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m retina.pipeline",
        description="Automated pre-processing of a folder of raw frames.")
    parser.add_argument("folder", help="folder of raw frames (walked recursively)")
    parser.add_argument("--preset", default="auto", choices=sorted(PRESETS),
                         help="pre-processing settings (default: auto)")
    parser.add_argument("--out", default=None,
                         help="output folder (default: <folder>/retina_pipeline)")
    parser.add_argument("--force", action="store_true",
                         help="recompute everything, ignoring the cache")
    parser.add_argument("--plan-only", action="store_true",
                         help="display the plan and stop there")
    parser.add_argument("--save-plan", metavar="FILE", default=None,
                         help="write the plan as JSON (editable, replayable)")
    args = parser.parse_args(argv)

    load_builtin()
    inventory = scan(args.folder)
    print(inventory)
    if not len(inventory):
        print("No frame recognized.", file=sys.stderr)
        return 1

    plan = build_plan(inventory, args.preset, output_dir=args.out)
    print(plan.describe())
    if args.save_plan:
        plan.save(args.save_plan)
        print(f"Plan written: {args.save_plan}")
    if args.plan_only:
        return 0

    report = run_plan(plan, on_progress=_bar, force=args.force)
    if sys.stderr.isatty():
        sys.stderr.write("\r" + " " * 90 + "\r")
    print(report.describe())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
