"""Fetch the ASTAP bundle (CLI solver + D05 star database) into ``vendor/astap/``.

ASTAP is the OFFLINE plate-solving backend on **Windows** (see
``retina.processes.astrometry.PlateSolve``, backend ``astap``). On Linux/macOS, retina uses
the ``astrometry`` Python package instead (which builds natively), so this script targets
Windows by default.

The binaries (~105 MB with the D05 database) are not versioned: this script downloads them.

Usage:
    python scripts/fetch_astap.py            # current platform (win64 by default on Windows)
    python scripts/fetch_astap.py --platform win64
    python scripts/fetch_astap.py --database d20   # narrower field (FOV > 0.3°)

ASTAP: © Han Kleijn, MPL 2.0 licence — www.hnsky.org. The star databases are freely
redistributable. Compatible with retina's GPL-3.0.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

SF = "https://sourceforge.net/projects/astap-program/files"

# Stripped CLI (solving only) per platform → (vendor subfolder, SourceForge file)
CLI = {
    "win64": ("win64", "windows_installer/astap_command-line_version_win64.zip"),
    "win32": ("win32", "windows_installer/astap_command-line_version_win32.zip"),
    "linux": ("linux", "linux_installer/astap_command-line_version_Linux_amd64.zip"),
    "macos": ("macos", "macOS installer/astap_command-line_version_macOS_x86_64.zip"),
}
# Star databases (current D series): useful FOV range + approximate size.
DB = {
    "d05": ("star_databases/d05_star_database.zip", "FOV > 0.6°  (~102 MB)"),
    "d20": ("star_databases/d20_star_database.zip", "FOV > 0.3°  (~400 MB)"),
    "d50": ("star_databases/d50_star_database.zip", "FOV > 0.2°  (~900 MB)"),
    "w08": ("star_databases/w08_star_database.zip", "FOV > 20°   (~0.6 MB)"),
}


def _download(sf_path: str, dest: Path) -> None:
    """Download a SourceForge file (through curl -L when available, urllib otherwise)."""
    url = f"{SF}/{sf_path}/download"
    print(f"  ↓ {sf_path}")
    if shutil.which("curl"):
        subprocess.run(["curl", "-L", "--fail", "--silent", "--show-error",
                        "-o", str(dest), url], check=True)
    else:  # fallback: urllib with a browser User-Agent (SourceForge filters otherwise)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    if dest.stat().st_size < 10_000 or dest.read_bytes()[:2] != b"PK":
        raise RuntimeError(f"Invalid download (not a zip): {sf_path}")


def _download_and_extract(sf_path: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        z = Path(tmp) / "dl.zip"
        _download(sf_path, z)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(out_dir)


def main() -> int:
    default_plat = {"win32": "win64", "darwin": "macos"}.get(sys.platform, "linux")
    ap = argparse.ArgumentParser(description="Download the ASTAP bundle into vendor/astap/")
    ap.add_argument("--platform", choices=sorted(CLI), default=default_plat)
    ap.add_argument("--database", choices=sorted(DB), default="d05")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    subdir, cli_path = CLI[args.platform]
    out = root / "vendor" / "astap" / subdir

    print(f"ASTAP bundle → {out}  (platform {args.platform}, database {args.database})")
    print("CLI:")
    _download_and_extract(cli_path, out)
    db_path, note = DB[args.database]
    print(f"{args.database.upper()} star database — {note}:")
    _download_and_extract(db_path, out)

    exe = "astap_cli.exe" if args.platform.startswith("win") else "astap_cli"
    ok = (out / exe).exists()
    print(f"{'✓' if ok else '✗'} {out / exe}")
    print("Done." if ok else "Failed: executable not found after extraction.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
