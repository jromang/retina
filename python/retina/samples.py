"""Sample datasets — manifest, local cache, verified download.

One does not discover a preprocessing package without raw frames. Yet whoever installs it on
a cloudy night does not necessarily have any at hand, and whoever does hesitates to run an
unknown chain on their own exposures. Hence these datasets: real observatory frames, under a
free license, that give something to stack within five minutes.

Nothing travels in the wheel — 162 MB for the smallest. The repository versions only the
**manifest** (``resources/samples.json``): what exists, where to get it, how to recognize it.
The archives land under ``cache_dir()/samples/<id>/``, outside the configuration folder,
because this is reloadable data and not settings — erasing it costs only a download.

# What this module shares with :mod:`retina.ai.models`, and what it does not

The download loop is the same in principle: one-megabyte blocks, SHA-256 digest computed **on
the fly** rather than by re-reading the file, writing into a ``.part`` renamed at the end,
progress and cancellation through the current thread's ``ProgressMonitor``. It is rewritten
here rather than factored out, for two reasons:

1. the unit is not the same — a model is **one file**, a sample dataset is an **archive to
   extract** into a folder about which one must then be able to say whether it is complete;
   half the work (extraction, marker, archive root) has no equivalent;
2. the refactoring would have touched ``ai/models.py``, outside the scope of this change.

If a third caller appears, that is the signal: extract a ``retina/download.py`` carrying the
loop then, and move both onto it.

# The marker

A half-extracted folder is indistinguishable from a complete one — the user cut the power,
twenty files out of thirty-two remain, and preprocessing will run on a truncated night
without reporting anything. The module therefore drops a marker (``.retina-sample.json``)
**after** the extraction, and it is that marker, never the existence of the folder, that
answers :func:`is_downloaded`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .i18n import translate as _t
from .paths import cache_path

#: manifest schema version. A file with a more recent schema is refused rather than read
#: crookedly.
SCHEMA = 1

#: environment variable pointing at a replacement manifest (tests, homemade datasets).
ENV_MANIFEST = "RETINA_SAMPLES_MANIFEST"

#: block size. Large enough not to pay the system call, small enough that progress advances
#: visibly and cancellation bites quickly.
_CHUNK = 1 << 20

#: marker dropped after a successful extraction — see the module header.
STAMP = ".retina-sample.json"


@dataclass(frozen=True)
class SampleSpec:
    """One manifest entry."""

    id: str
    name: str
    url: str
    sha256: str
    size: int = 0
    license: str = ""
    attribution: str = ""
    homepage: str = ""
    #: permanent identifier of the publication (Zenodo DOI…). It is what guarantees the URL
    #: will still be worth something in five years, not the domain name.
    doi: str = ""
    note: str = ""

    @property
    def label(self) -> str:
        return self.name or self.id


def manifest_path() -> Path:
    """Path of the manifest: the environment's, otherwise the embedded one."""
    override_ = os.environ.get(ENV_MANIFEST, "").strip()
    if override_:
        return Path(override_)
    return Path(__file__).resolve().parent / "resources" / "samples.json"


#: manifest as read, indexed by (path, mtime) — same reason as for the models: the catalogue
#: is re-read every time the home screen is displayed.
_CACHE: dict[tuple, tuple[tuple[SampleSpec, ...], str]] = {}


def _load(path: str | os.PathLike | None = None) -> tuple[tuple[SampleSpec, ...], str]:
    """``(entries, default id)``. A missing file returns an empty catalogue, never an error."""
    resolved = Path(path) if path is not None else manifest_path()
    try:
        mtime = resolved.stat().st_mtime
    except OSError:
        return (), ""
    key = (str(resolved), mtime)
    known = _CACHE.get(key)
    if known is not None:
        return known

    raw_data = json.loads(resolved.read_text(encoding="utf-8"))
    schema = int(raw_data.get("schema", 0))
    if schema > SCHEMA:
        raise ValueError(
            _t("sample manifest in schema {schema}, known up to {known} - "
               "please update Retina").format(schema=schema, known=SCHEMA))
    fields = set(SampleSpec.__dataclass_fields__)
    specs = tuple(
        SampleSpec(**{k: v for k, v in entry.items() if k in fields})
        for entry in raw_data.get("samples", ())
    )
    default = str(raw_data.get("default", "") or (specs[0].id if specs else ""))
    _CACHE[key] = (specs, default)
    return specs, default


def load_manifest(path: str | os.PathLike | None = None) -> tuple[SampleSpec, ...]:
    """The manifest entries, in their declaration order."""
    return _load(path)[0]


def catalog() -> list[SampleSpec]:
    """Every dataset on offer — ``retina.samples.catalogue()`` in the console."""
    return list(load_manifest())


def default_id() -> str:
    """The dataset offered when none is designated (the home screen's card).

    Declared in the manifest rather than deduced from the order: the smallest is not
    necessarily the first written, and the smallest is the one to put in front of a beginner.
    """
    return _load()[1]


def spec(sample_id: str) -> SampleSpec:
    tout = catalog()
    for sample in tout:
        if sample.id == sample_id:
            return sample
    connus = ", ".join(s.id for s in tout) or _t("none")
    raise KeyError(_t("unknown sample dataset: {id!r} (available: {known})")
                   .format(id=sample_id, known=connus))


def _resolved(sample_id: str) -> str:
    """An empty identifier means "the default one" — the call of a client that knows none."""
    return sample_id or default_id()


def resolve_id(sample_id: str = "") -> str:
    """The effective identifier of a call, with the default resolved.

    Public because the echo needs it: the home screen's card calls with nothing, and a
    console writing ``app.download_sample('')`` would not tell which dataset was just
    downloaded. It therefore writes the resolved name, which is replayable as is.
    """
    return _resolved(sample_id)


# --------------------------------------------------------------------------- #
# Local location                                                               #
# --------------------------------------------------------------------------- #
def sample_dir(sample_id: str) -> Path:
    """Where this dataset lives once extracted (the host folder, not yet the data)."""
    return Path(cache_path("samples", _resolved(sample_id)))


def path(sample_id: str) -> Path:
    """The **data** folder: the one containing the FITS.

    Archives in the wild almost always wrap their content in a single folder
    (``example-cryo-LFC/``). Returning the host folder would point preprocessing one step too
    high, where it would only see a subfolder; we therefore descend one level when there is
    only one child. The rule is deduced from what is on disk rather than declared in the
    manifest: one more field would be one more field to be made to lie.

    Dot-initial entries are ignored in that count, and not only our marker: an archive made
    on macOS carries its AppleDouble files (``._name``, ``.DS_Store``) next to the useful
    folder, and two children instead of one would be enough to break the rule.
    """
    root = sample_dir(sample_id)
    entries = [e for e in root.iterdir() if not e.name.startswith(".")] \
        if root.is_dir() else []
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return root


def is_downloaded(sample_id: str) -> bool:
    """True only if the extraction ran to completion (see the marker, at the top)."""
    return (sample_dir(sample_id) / STAMP).is_file()


def sha256_of(target: str | os.PathLike) -> str:
    """Digest of a file, read in blocks."""
    digest = hashlib.sha256()
    with open(target, "rb") as f:
        while block := f.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# Download and extraction                                                      #
# --------------------------------------------------------------------------- #
def _extract(archive: Path, destination: Path, monitor) -> None:
    """Unpack the archive into *destination*, never leaving it.

    ``filter="data"`` (tarfile) and the explicit name check (zipfile) are what prevent a
    hostile — or merely badly made — archive from writing elsewhere in the user's tree. The
    manifest is ours and the digests are verified before getting here; that is no reason to
    unpack a file from the network on trust.

    The format is **sniffed** and not deduced from the name: at this stage the file is called
    ``<id>.part``, and the original extension lives only in the URL — which a mirror or a
    content link (Zenodo returns ``…/files/<name>/content``) is not required to preserve.
    """
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            members = zf.namelist()
            for rank, name in enumerate(members, 1):
                target = (destination / name).resolve()
                if destination.resolve() not in target.parents:
                    raise ValueError(
                        _t("archive entry escapes its folder: {name!r}").format(name=name))
                zf.extract(name, destination)
                _progress(monitor, rank, len(members))
        return
    with tarfile.open(archive, mode="r:*") as tf:
        members = tf.getmembers()
        for rank, membre in enumerate(members, 1):
            tf.extract(membre, destination, filter="data")
            _progress(monitor, rank, len(members))


def _progress(monitor, rank: int, total: int) -> None:
    if monitor is not None:
        # `report` does the cancellation checkpoint itself: nothing more to place.
        monitor.report(rank / total if total else None,
                        _t("Extracting {done}/{total}").format(done=rank, total=total))


def download(sample_id: str = "", *, force: bool = False) -> Path:
    """Download the dataset, verify its digest, extract it. Returns the data folder.

    Progress and cancellation go through the current thread's
    :class:`~retina.process.progress.ProgressMonitor`, as for a process.

    An interrupted run leaves **nothing** recoverable: no ``.part``, which the next attempt
    would take for a download in progress, and no half-extracted folder, which would pass for
    a complete dataset.
    """
    from .process import context

    identifier = _resolved(sample_id)
    definition = spec(identifier)
    target = sample_dir(identifier)
    if is_downloaded(identifier) and not force:
        return path(identifier)

    shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    monitor = context.get_monitor()
    _notify(_t("Downloading {label}…").format(label=definition.label), "info")

    digest = hashlib.sha256()
    lus = 0
    try:
        request = urllib.request.Request(definition.url, headers={"User-Agent": "retina"})
        with urllib.request.urlopen(request) as flux, open(partial, "wb") as output:
            total = int(flux.headers.get("Content-Length") or definition.size or 0)
            while block := flux.read(_CHUNK):
                output.write(block)
                digest.update(block)
                lus += len(block)
                if monitor is not None:
                    monitor.report(lus / total if total else None,
                                    f"{definition.label} — {lus // (1 << 20)} Mio")
        checksum = digest.hexdigest()
        if definition.sha256 and checksum != definition.sha256:
            raise ValueError(
                _t("wrong fingerprint for sample {id!r}: expected {expected}, got {got}. "
                   "File discarded.").format(id=identifier, expected=definition.sha256,
                                             got=checksum))
        _extract(partial, target, monitor)
        (target / STAMP).write_text(
            json.dumps({"id": identifier, "sha256": checksum, "url": definition.url,
                        "license": definition.license, "attribution": definition.attribution},
                       indent=2),
            encoding="utf-8")
    except BaseException:
        # Also holds for cancellation, which is not an `Exception` but a cooperative
        # interruption: a folder surviving a failure would be taken for a usable dataset.
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        partial.unlink(missing_ok=True)

    _notify(_t("{label} is ready in {path}").format(label=definition.label,
                                                      path=path(identifier)), "info")
    return path(identifier)


def ensure(sample_id: str = "") -> Path:
    """Data folder of the dataset, downloaded on demand if it is missing."""
    identifier = _resolved(sample_id)
    spec(identifier)  # raises right away if the identifier is unknown
    if is_downloaded(identifier):
        return path(identifier)
    return download(identifier)


def _notify(message: str, kind: str) -> None:
    """Trace into the notification center, if an application is there to hear it."""
    from .process import context

    try:
        app = context.get_application()
        if app is not None:
            app.notify(message, kind=kind, source="retina.samples")
    except Exception:  # headless with no application, or center unavailable: unimportant
        pass
