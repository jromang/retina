"""Spectral curves — filter transmission, sensor efficiency, white references.

Spectrophotometric color calibration needs to know *what the telescope actually saw*: the
filter's transmission, the sensor's quantum efficiency, and the spectrum we decree white.
Without those three curves, one can only assume nominal passbands — which is what
``SpectrophotometricColorCalibration`` did until now, with a hard-coded 3×3 matrix.

# The format, and why that one

One CSV per curve, two ``wavelength_nm,value`` columns, preceded by a few ``# key: value``
lines. It is readable, it diffs in review, it edits by hand, and it goes into the wheel with
no extra packaging rule (``resources/**`` is already taken as is). A binary format would have
saved a few kilobytes against any possibility of inspection.

# Where the embedded curves come from

From the `siril-spcc-database <https://gitlab.com/free-astro/siril-spcc-database>`_ database,
under **GPL-3** hence compatible with ours, measured and verified by the Siril community from
manufacturer documents. Each file cites its source and its license in its header, and
``scripts/fetch_spectra.py`` says which ones are taken and why.

The user's curves live under ``config_dir()/spectra/`` and **shadow** the embedded namesake:
that is what makes it possible to correct a curve one judges wrong without patching the
installation.

# What is not here

Narrowband filters. A 3 or 7 nm band read off a scanner is less precise than the same band
described analytically by its central wavelength and its width — hence
:func:`boxcar_response`, and not a file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .i18n import translate as _t
from .paths import config_path

#: curve families, and each one's subfolder
KINDS: dict[str, str] = {
    "filter": "filters",
    "sensor": "sensors",
    "white_reference": "whiteref",
}

#: headers recognized in a curve file (the others are kept but ignored)
_HEADERS = ("name", "kind", "channel", "manufacturer", "source", "origin", "license")

_BUNDLED = Path(__file__).resolve().parent / "resources" / "spectra"


@dataclass(frozen=True)
class CurveInfo:
    """What is known about a curve without having loaded it."""

    id: str
    kind: str
    name: str = ""
    channel: str = ""
    manufacturer: str = ""
    source: str = ""
    license: str = ""
    user: bool = False
    path: Path | None = None

    @property
    def label(self) -> str:
        return self.name or self.id


def _folder(kind: str, *, user: bool) -> Path:
    if kind not in KINDS:
        raise ValueError(_t("unknown curve family: {kind!r} (known: {known})")
                         .format(kind=kind, known=sorted(KINDS)))
    if user:
        return Path(config_path("spectra", KINDS[kind]))
    return _BUNDLED / KINDS[kind]


def _header(path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            key, _, value = line[1:].partition(":")
            key = key.strip().lower()
            if key in _HEADERS:
                meta[key] = value.strip()
    return meta


def list_curves(kind: str | None = None) -> list[CurveInfo]:
    """Every available curve, the user's first.

    A user curve with the same identifier **replaces** the embedded one: the list carries
    only one, the one that will actually be loaded.
    """
    families = [kind] if kind else list(KINDS)
    found_items: dict[tuple[str, str], CurveInfo] = {}
    for family in families:
        # The embedded ones first, the user's next: the second overwrites the first.
        for user in (False, True):
            folder = _folder(family, user=user)
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.csv")):
                meta = _header(path)
                found_items[(family, path.stem)] = CurveInfo(
                    id=path.stem, kind=family, name=meta.get("name", ""),
                    channel=meta.get("channel", ""),
                    manufacturer=meta.get("manufacturer", ""),
                    source=meta.get("source", ""), license=meta.get("license", ""),
                    user=user, path=path,
                )
    return sorted(found_items.values(), key=lambda c: (c.kind, c.id))


def curve_info(name: str, kind: str) -> CurveInfo:
    for info in list_curves(kind):
        if info.id == name:
            return info
    connues = ", ".join(c.id for c in list_curves(kind)) or _t("none")
    raise KeyError(_t("unknown {kind} curve: {name!r} (available: {available})")
                   .format(kind=kind, name=name, available=connues))


#: curves as read, indexed by (path, mtime) — a curve is re-read when its file changes, which
#: makes editing through ``FilterManager`` visible without a restart.
_CACHE: dict[tuple[str, float], np.ndarray] = {}


def load_curve(name: str, kind: str) -> np.ndarray:
    """The ``(N, 2)`` curve — wavelength in nm, value — sorted by wavelength."""
    path = curve_info(name, kind).path
    assert path is not None
    key = (str(path), path.stat().st_mtime)
    connue = _CACHE.get(key)
    if connue is not None:
        return connue
    points = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line[0].isalpha():
                continue        # header, empty line, or the column titles line
            lam, _, val = line.partition(",")
            points.append((float(lam), float(val)))
    if not points:
        raise ValueError(_t("empty curve: {path}").format(path=path))
    curve = np.asarray(sorted(points), dtype=np.float64)
    curve[:, 1] = _as_fraction(curve[:, 1], kind)
    _CACHE[key] = curve
    return curve


def _as_fraction(values: np.ndarray, kind: str) -> np.ndarray:
    """Bring transmissions and efficiencies back into [0, 1], however they are given.

    Manufacturer documents use both scales, and the upstream database takes them as they
    come: Baader and ZWO in percent, Chroma and Optolong as fractions. Mixing them would give
    a channel response a hundred times too large — without anything breaking, since the
    calibration gains are ratios. The criterion is clear-cut in practice: a transmission does
    not exceed 1 as a fraction, and is worth tens in percent.

    The **white references** are not concerned: they are spectra, of arbitrary scale, for
    which a maximum above 1 is perfectly normal.
    """
    if kind == "white_reference":
        return values
    return values / 100.0 if float(values.max()) > 1.5 else values


def resample(curve: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Resample a curve onto a grid of wavelengths.

    Outside the curve's support the result is **zero**, not extended: a filter whose
    transmission is known only from 400 to 700 nm transmits nothing we know of beyond, and
    extending by the edge would invent an infrared tail for it.
    """
    grid_values = np.asarray(grid, dtype=np.float64)
    values = np.interp(grid_values, curve[:, 0], curve[:, 1], left=0.0, right=0.0)
    return np.clip(values, 0.0, None)


def channel_response(filter_name: str, sensor_name: str, grid: np.ndarray) -> np.ndarray:
    """A channel's response: filter transmission × sensor efficiency.

    An empty filter name means "no filter" (transmission 1), an empty sensor name "perfect
    sensor" (efficiency 1) — enough to isolate the effect of either.
    """
    response = np.ones_like(np.asarray(grid, dtype=np.float64))
    if filter_name:
        response = response * resample(load_curve(filter_name, "filter"), grid)
    if sensor_name:
        response = response * resample(load_curve(sensor_name, "sensor"), grid)
    return response


def boxcar_response(center_nm: float, width_nm: float, grid: np.ndarray) -> np.ndarray:
    """Rectangular passband — the way a narrowband filter is described.

    More accurate than a measured curve: the width announced by the manufacturer is a datum,
    the reading of a scanned graph is an approximation of it.
    """
    grid_values = np.asarray(grid, dtype=np.float64)
    half = max(float(width_nm), 1e-6) / 2.0
    return ((grid_values >= center_nm - half)
            & (grid_values <= center_nm + half)).astype(np.float64)


def save_user_curve(name: str, kind: str, points: Sequence[Sequence[float]], *,
                    label: str = "", channel: str = "") -> Path:
    """Write a user curve under ``config_dir()/spectra/``. Returns its path."""
    pairs = sorted((float(a), float(b)) for a, b in points)
    if len(pairs) < 2:
        raise ValueError(_t("a curve needs at least two points"))
    folder = _folder(kind, user=True)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{name}.csv"
    lines = [
        f"# name: {label or name}",
        f"# kind: {kind}",
        f"# channel: {channel}",
        "# source: user",
        "wavelength_nm,value",
        *(f"{a:g},{b:g}" for a, b in pairs),
    ]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def delete_user_curve(name: str, kind: str) -> bool:
    """Remove a user curve. The embedded namesake becomes visible again."""
    target = _folder(kind, user=True) / f"{name}.csv"
    if not target.exists():
        return False
    target.unlink()
    return True
