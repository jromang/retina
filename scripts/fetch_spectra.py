#!/usr/bin/env python3
"""Import the embedded spectral-curve database from Siril's SPCC database.

A **deliberate** act, like ``gen_web_fixtures.py`` or ``gen_icons.py``: nothing runs it
automatically, and its output is versioned.

# Where these curves come from, and why we are allowed to ship them

The synthetic photometry of ``SpectrophotometricColorCalibration`` needs three families of
curves: **filter transmissions**, **sensor quantum efficiencies** and **white references**.
Nobody measures those themselves: they are manufacturer data, collected and then vetted by a
community.

The `free-astro/siril-spcc-database <https://gitlab.com/free-astro/siril-spcc-database>`_
database is exactly that, and it is under **GPL-3** — hence compatible with Retina's licence
(GPL-3.0-or-later). We may redistribute it; we must cite its source and its licence, which
every generated file does in its header.

# What we embed, and what we do not

A **subset**: the upstream database holds more than two hundred curves, many of them for old
camera bodies. Embedding them all would bloat the wheel for rare cases, whereas the same
database can be imported on demand into ``config_dir()/spectra/`` through ``FilterManager``.
The selection covers what one actually meets: the common CMOS sensors, the RGB sets of the
main manufacturers, and the useful white references.

**Narrowband filters are not taken** — they are synthesised analytically from a wavelength and
a bandwidth (``spectra.boxcar_response``), which is more accurate than a curve read off a
scanner. Siril makes the same choice.

Usage:
    python scripts/fetch_spectra.py            # import the embedded subset
    python scripts/fetch_spectra.py --list     # say what exists upstream, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from _console import configure as _configure_console

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "python" / "retina" / "resources" / "spectra"

PROJECT = "free-astro%2Fsiril-spcc-database"
BRANCH = "main"
SOURCE = "https://gitlab.com/free-astro/siril-spcc-database"
LICENSE = "GPL-3.0-or-later"

#: Embedded subset: (upstream folder, file, local subfolder).
#: Color sensors are filed with the sensors — a sensor stays a sensor; what changes is the
#: presence of a Bayer matrix, not the nature of the curve.
SELECTION = [
    # --- monochrome sensors ---
    ("mono_sensors", "Generic_mono", "sensors"),
    ("mono_sensors", "Sony_IMX183", "sensors"),
    ("mono_sensors", "Sony_IMX585", "sensors"),
    ("mono_sensors", "KAF_8300", "sensors"),
    # --- color sensors (the CMOS most widespread in astro) ---
    ("osc_sensors", "Sony_IMX571", "sensors"),
    ("osc_sensors", "Sony_IMX533", "sensors"),
    ("osc_sensors", "Sony_IMX455", "sensors"),
    ("osc_sensors", "Sony_IMX294", "sensors"),
    ("osc_sensors", "ZWO_Seestar_S50", "sensors"),
    # --- monochrome RGB filter sets ---
    ("mono_filters", "Baader_LRGB", "filters"),
    ("mono_filters", "Astronomik_DeepSky_RGB", "filters"),
    ("mono_filters", "Chroma_RGB", "filters"),
    ("mono_filters", "Antlia_LRGB-V_Pro", "filters"),
    ("mono_filters", "ZWO_new_LRGB", "filters"),
    ("mono_filters", "Optolong_RGB", "filters"),
    ("mono_filters", "Johnson_photometric", "filters"),
    ("mono_filters", "SDSS", "filters"),
    # --- white references ---
    ("wb_refs", "Average_spiral_galaxy", "whiteref"),
    ("wb_refs", "Sb", "whiteref"),
    ("wb_refs", "Star_g2v", "whiteref"),
    ("wb_refs", "Star_a0v", "whiteref"),
]


def _read(path: str) -> str:
    url = (f"https://gitlab.com/api/v4/projects/{PROJECT}/repository/files/"
           f"{urllib.parse.quote(path, safe='')}/raw?ref={BRANCH}")
    request = urllib.request.Request(url, headers={"User-Agent": "retina/1.0"})
    with urllib.request.urlopen(request, timeout=60) as stream:
        return stream.read().decode("utf-8", "replace")


def _tree(folder: str) -> list[str]:
    url = (f"https://gitlab.com/api/v4/projects/{PROJECT}/repository/tree"
           f"?path={folder}&per_page=100&ref={BRANCH}")
    request = urllib.request.Request(url, headers={"User-Agent": "retina/1.0"})
    with urllib.request.urlopen(request, timeout=60) as stream:
        entries = json.loads(stream.read().decode())
    return [e["path"] for e in entries if e["type"] == "blob"]


def _slug(text: str) -> str:
    kept = [c.lower() if c.isalnum() else "_" for c in text]
    return "_".join("".join(kept).split("_")).strip("_")


def _series(block) -> list[float]:
    """The numbers of a field, be it a bare list or an object ``{value, units}``.

    The upstream schema uses both forms depending on the field and the contributor; iterating a
    dict naively would yield its *keys*, which fails on ``float('value')`` — loudly, thankfully.
    """
    if isinstance(block, dict):
        block = block.get("value", [])
    return [float(v) for v in block]


def _nanometers(entry: dict) -> list[float]:
    """Wavelengths in nanometres, whatever unit is declared upstream."""
    block = entry["wavelength"]
    values = _series(block)
    unit = str(block.get("units", "nm") if isinstance(block, dict) else "nm").lower()
    if unit.startswith("a"):          # angstroms
        return [v / 10.0 for v in values]
    if unit.startswith("m") and "n" not in unit:   # micrometres
        return [v * 1000.0 for v in values]
    return values


def _write(folder: Path, name: str, entry: dict, kind: str, upstream_path: str) -> Path:
    lam = _nanometers(entry)
    val = _series(entry["values"])
    if len(lam) != len(val):
        raise ValueError(f"{name}: {len(lam)} wavelengths for {len(val)} values")
    pairs = sorted(zip(lam, val, strict=True))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.csv"
    lines = [
        f"# name: {entry.get('name', name)}",
        f"# kind: {kind}",
        f"# channel: {(entry.get('channel') or '').lower()}",
        f"# manufacturer: {entry.get('manufacturer', '')}",
        f"# source: {SOURCE}/-/blob/{BRANCH}/{upstream_path}",
        f"# origin: {entry.get('dataSource', '')}",
        f"# license: {LICENSE}",
        "wavelength_nm,value",
        *(f"{a:g},{b:g}" for a, b in pairs),
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def import_subset() -> int:
    written = 0
    for folder, file, local in SELECTION:
        path = f"{folder}/{file}.json"
        try:
            raw_data = json.loads(_read(path))
        except Exception as exc:  # a file missing upstream is not fatal
            print(f"[spectra] ⚠ {path}: {exc}")
            continue
        entries = raw_data if isinstance(raw_data, list) else [raw_data]
        for entry in entries:
            kind = {"filters": "filter", "sensors": "sensor",
                    "whiteref": "white_reference"}[local]
            # A filter set carries several channels in a single file; so does a color sensor.
            # The upstream **name** already tells them apart ("Antlia R", "Sony IMX571 Blue"):
            # the channel stays metadata, in the header, and not in the file name — putting it
            # there produced "chroma_blue_blue" and, for SDSS whose channel is called
            # "BLUE GREEN", a space inside a file name.
            channel = entry.get("channel")
            name = _slug(entry.get("name") or file)
            try:
                target = _write(OUTPUT / local, name, entry, kind, path)
            except Exception as exc:
                print(f"[spectra] ⚠ {path} ({channel}): {exc}")
                continue
            print(f"[spectra] {target.relative_to(ROOT)}")
            written += 1
    print(f"[spectra] {written} curves written under {OUTPUT.relative_to(ROOT)}")
    return 0


def list_upstream() -> int:
    for folder in ("mono_filters", "osc_filters", "mono_sensors", "osc_sensors", "wb_refs"):
        names = [Path(p).stem for p in _tree(folder)]
        print(f"--- {folder} ({len(names)}) ---")
        print("  " + ", ".join(sorted(names)))
    return 0


def main() -> int:
    _configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                         help="list what exists upstream, write nothing")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return list_upstream() if args.list else import_subset()


if __name__ == "__main__":
    raise SystemExit(main())
