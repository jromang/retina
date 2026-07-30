"""Credits and licenses — what Retina embeds, and under which conditions.

A free software package that does not say what it redistributes holds up its side of the
bargain poorly. Three audiences need this page, and not for the same reasons:

- **the authors** of what we use — most permissive licenses explicitly require their
  copyright notice to travel with the code; that is the price, and it is a small one;
- **the user**, who has no way to guess that a model downloaded from a panel forbids them
  commercial use (that is the case of the GraXpert models, under CC BY-NC-SA);
- **whoever redistributes** Retina — a distribution packager, someone building a product out
  of it — and who must know what they are shipping along with it.

# Where the data comes from, and why from two places

The **Python dependencies** are enumerated at runtime, from the metadata of the installed
distributions (:mod:`importlib.metadata`). It is the only source that cannot lie: it
describes what is really there, version included, extras the user chose included. A
hand-maintained list would have drifted on the first ``pip install``.

Everything else comes from a **versioned manifest** (``resources/credits.json``), because
introspection does not see it: the assets copied into the repository, the npm packages Vite
inlines into a single bundle, the crates Cargo links statically into the shell, and what is
downloaded on demand without ever passing through the wheel. A guard
(``tests/test_credits.py``) checks that the manifest really covers what is on disk.

Pure domain: stdlib alone. ``app.credits()`` is therefore readable from the console like the
rest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .i18n import translate as _t

#: component families, in the order we want them read
KINDS = ("asset", "frontend", "native", "python", "download")

_RESOURCES = Path(__file__).resolve().parent / "resources"
_MANIFEST = _RESOURCES / "credits.json"

#: Python distributions to credit: those the project declares, plus what they pull in. We
#: start from our own declarations rather than from the whole environment — a `pip list` in a
#: development venv contains pytest, ruff and mypy, which are not shipped.
_ROOTS = (
    "numpy", "astropy", "asteval", "PyYAML",
    "aiohttp", "ipython", "markdown", "pymdown-extensions", "pygments", "pillow",
    "scipy", "scikit-image", "photutils", "ccdproc", "astroalign", "astroscrappy",
    "colour-demosaicing", "astroquery", "astrometry", "matplotlib", "reproject", "sep",
    "PyWavelets", "rawpy", "opencv-python-headless", "scikit-learn",
    # Both CuPy wheels are listed because a machine installs only one, depending on its CUDA
    # branch: citing only one would silence the credit on the other half of the machines.
    "onnxruntime", "cupy-cuda12x", "cupy-cuda13x", "xisf", "h5py",
    "tifffile", "imageio", "pillow-jxl-plugin", "jplephem",
)


@dataclass(frozen=True)
class Credit:
    """A third-party component Retina embeds or downloads."""

    id: str
    name: str
    kind: str
    license: str = ""
    version: str = ""
    copyright: str = ""
    url: str = ""
    notice: str = ""      # path relative to resources/, if a full notice exists
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "kind": self.kind, "license": self.license,
            "version": self.version, "copyright": self.copyright, "url": self.url,
            "notice": self.notice, "note": self.note,
        }


def _manifeste() -> list[Credit]:
    try:
        raw_data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    fields = set(Credit.__dataclass_fields__)
    return [Credit(**{k: v for k, v in entry.items() if k in fields})
            for entry in raw_data.get("components", ())]


def _licence_declaree(metadonnees) -> str:
    """A distribution's license, as it deigns to declare itself.

    Three forms coexist in the wild: the ``License-Expression`` field (PEP 639, the clean
    one), the ``License :: …`` classifiers (historical usage), and the free-form ``License``
    field — which sometimes contains the **entire text** of the license. We take the first
    that makes sense, and truncate the last: displaying three hundred lines in a table cell
    helps nobody.
    """
    expression = metadonnees.get("License-Expression")
    if expression:
        return str(expression).strip()
    classifieurs = [c for c in metadonnees.get_all("Classifier") or ()
                    if c.startswith("License ::")]
    if classifieurs:
        # "License :: OSI Approved :: BSD License" → "BSD License"
        return classifieurs[0].rsplit("::", 1)[-1].strip()
    free = (metadonnees.get("License") or "").strip()
    if not free:
        return ""
    first = free.splitlines()[0].strip()
    return first if len(first) <= 60 else first[:57] + "…"


def python_dependencies() -> list[Credit]:
    """The Python distributions actually installed, among those the project declares.

    An absent dependency (an extra not installed) is simply omitted: the page describes the
    installation at hand, not the one one might have had.
    """
    from importlib import metadata

    credits_: list[Credit] = []
    for name in _ROOTS:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        meta = dist.metadata
        urls = meta.get_all("Project-URL") or []
        lien = meta.get("Home-page") or ""
        if not lien and urls:
            lien = str(urls[0]).split(",", 1)[-1].strip()
        credits_.append(Credit(
            id=name.lower(), name=meta.get("Name") or name, kind="python",
            license=_licence_declaree(meta), version=dist.version or "",
            url=lien,
        ))
    return sorted(credits_, key=lambda c: c.name.lower())


def all_credits() -> list[Credit]:
    """Everything, manifest and Python dependencies together, grouped by family."""
    tout = _manifeste() + python_dependencies()
    order = {kind: i for i, kind in enumerate(KINDS)}
    return sorted(tout, key=lambda c: (order.get(c.kind, 99), c.name.lower()))


def notice(credit_id: str) -> str:
    """The full text of a component's license, if one accompanies it.

    Many permissive licenses — MIT foremost — require their notice to travel with the code.
    Merely writing "MIT" somewhere is therefore not enough; the text is embedded, and this
    function is what returns it.
    """
    for credit in _manifeste():
        if credit.id == credit_id:
            if not credit.notice:
                raise KeyError(_t("no embedded notice for {id!r}").format(id=credit_id))
            return (_RESOURCES / credit.notice).read_text(encoding="utf-8")
    raise KeyError(_t("unknown component: {id!r}").format(id=credit_id))


def summary() -> dict[str, int]:
    """How many components per family — enough to check at a glance."""
    count: dict[str, int] = {}
    for credit in all_credits():
        count[credit.kind] = count.get(credit.kind, 0) + 1
    return count


def to_text() -> str:
    """The credits as plain text — for the console, a README or a bug report."""
    lines = ["Retina — third-party components", ""]
    families = {
        "asset": "Embedded resources",
        "frontend": "Frontend (included in the bundle)",
        "native": "Native shell and core (linked)",
        "python": "Installed Python dependencies",
        "download": "Downloaded on demand (not redistributed)",
    }
    for kind in KINDS:
        group = [c for c in all_credits() if c.kind == kind]
        if not group:
            continue
        lines += [families.get(kind, kind), "-" * len(families.get(kind, kind))]
        for credit in group:
            version = f" {credit.version}" if credit.version else ""
            lines.append(f"  {credit.name}{version} — {credit.license or '?'}")
        lines.append("")
    return "\n".join(lines)
