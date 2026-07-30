"""AI model manifest, local cache, verified download.

No model travels inside the wheel: they weigh tens of megabytes and their licenses are not
ours. The repository versions only the **manifest** — a JSON file saying which models exist,
where to get them, and how to recognize them. They land in ``cache_dir()/models/``, outside the
configuration directory: they are re-downloadable data, not settings.

# Three ways to obtain a model, in order of preference

1. **Discovered locally** — if GraXpert is installed, :func:`discover_local` finds its models
   and uses them *in place*, copying nothing. This is the priority path: nothing to download,
   and the version follows GraXpert's.
2. **The bundled manifest** (``resources/models/manifest.json``) — the GraXpert models
   re-hosted **unchanged** on ``huggingface.co/jromanghf/graxpert-models``, each with its
   fingerprint. This is the fallback for anyone without GraXpert. We can do it because their
   license allows it: GraXpert's code is GPL-3, but its **models** are under
   **CC BY-NC-SA 4.0**, which permits redistribution with attribution — hence the credit in the
   HF repository card and in :mod:`retina.credits`. The license does forbid **commercial** use,
   which Retina itself does not restrict: the constraint comes from GraXpert and follows the
   model all the way into the FITS keywords.
3. **A supplied path** — ``model`` accepts any ``.onnx`` the user designates.

**StarNet** stays outside the manifest: its proprietary license permits neither redistribution
nor direct linking. It is reached through the local path, as before.

Whichever the route, traceability is the same — it is the fingerprint of the file actually used
that enters the history.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import translate as _t
from ..paths import cache_path

#: known tasks. A manifest declaring another one is not rejected — it will simply be offered
#: by no process.
TASKS = ("starless", "denoise", "deconv_object", "deconv_stellar", "background")

#: value of ``model_id`` meaning "the most recent for the task, chosen for me". It is the
#: default of the AI processes: opening the panel and running is enough, with no id to know.
LATEST = "latest"

#: version of the manifest schema. A file in a newer schema is refused rather than read
#: crooked.
SCHEMA = 1

#: environment variable pointing at a replacement manifest (tests, home-grown models).
ENV_MANIFEST = "RETINA_MODELS_MANIFEST"

#: download block size. Large enough not to pay for the system call, small enough for progress
#: to advance visibly and for cancellation to bite quickly.
_CHUNK = 1 << 20


@dataclass(frozen=True)
class ModelSpec:
    """One manifest entry."""

    id: str
    task: str
    name: str
    version: str
    url: str
    sha256: str
    size: int = 0
    license: str = ""
    homepage: str = ""
    extra_inputs: dict = field(default_factory=dict)
    #: local path, when the model is **already** on the machine (a detected GraXpert
    #: installation). When filled in, it short-circuits any download.
    path: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} {self.version}".strip()


#: Where GraXpert stores its models, by task. The names come from its
#: ``ai_model_handling.py``; each directory contains ``<version>/model.onnx``.
GRAXPERT_DIRS = {
    "background": "bge-ai-models",
    "denoise": "denoise-ai-models",
    "deconv_object": "deconvolution-object-ai-models",
    "deconv_stellar": "deconvolution-stars-ai-models",
}

#: environment variable pointing at a non-standard GraXpert installation (a portable version,
#: a directory shared between machines).
ENV_GRAXPERT = "RETINA_GRAXPERT_DIR"

#: License of the GraXpert models — **distinct** from the GPL-3 of their code. Free and
#: shareable, but forbidden for commercial use. It is carried all the way into the credits
#: because the user cannot guess it by clicking.
GRAXPERT_LICENSE = "CC-BY-NC-SA-4.0"


def graxpert_data_dirs() -> list[Path]:
    """The locations where GraXpert may have dropped its models, per platform.

    GraXpert uses ``appdirs.user_data_dir(appname="GraXpert")``; we reproduce its three
    resolutions rather than add a dependency for three lines. On Windows, appdirs repeats the
    application name twice when no author is given — hence the two variants, only one of which
    exists in practice.
    """
    override_ = os.environ.get(ENV_GRAXPERT, "").strip()
    if override_:
        return [Path(override_).expanduser()]
    maison = Path.home()
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", maison / "AppData" / "Local"))
        return [local / "GraXpert" / "GraXpert", local / "GraXpert"]
    if sys.platform == "darwin":
        return [maison / "Library" / "Application Support" / "GraXpert"]
    data = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(data) if data else maison / ".local" / "share"
    return [base / "GraXpert"]


def discover_local() -> list[ModelSpec]:
    """The models of a **GraXpert** installation found on this machine.

    A user who installed GraXpert already has its models; there is no reason to make them
    re-download ours. They therefore **take precedence** over the manifest (see
    :func:`catalog`), and are returned with their **local path**: nothing to download, nothing
    to verify by fingerprint since the file is already there. Traceability does not change — it
    is still the fingerprint of the file actually used that enters the history.
    """
    found_items: list[ModelSpec] = []
    for root in graxpert_data_dirs():
        if not root.is_dir():
            continue
        for task, folder in GRAXPERT_DIRS.items():
            base = root / folder
            if not base.is_dir():
                continue
            for version in sorted(base.iterdir()):
                model = version / "model.onnx"
                if not model.is_file():
                    continue
                found_items.append(ModelSpec(
                    id=f"graxpert-{task.replace('_', '-')}-{version.name}",
                    task=task, name=f"GraXpert {task.replace('_', ' ')}",
                    version=version.name, url="", sha256="",
                    size=model.stat().st_size, license=GRAXPERT_LICENSE,
                    homepage="https://github.com/Steffenhir/GraXpert",
                    path=str(model),
                ))
    return found_items


def manifest_path() -> Path:
    """Path of the manifest: the environment's, otherwise the bundled one."""
    override_ = os.environ.get(ENV_MANIFEST, "").strip()
    if override_:
        return Path(override_)
    return Path(__file__).resolve().parent.parent / "resources" / "models" / "manifest.json"


#: manifest read, keyed by (path, mtime) — re-reading a JSON on every `available()` would cost
#: dearly in the construction of a process's `choices`.
_CACHE: dict[tuple, tuple[ModelSpec, ...]] = {}


def load_manifest(path: str | os.PathLike | None = None) -> tuple[ModelSpec, ...]:
    """Load the manifest. A missing file returns an empty catalog, never an error."""
    resolved = Path(path) if path is not None else manifest_path()
    try:
        mtime = resolved.stat().st_mtime
    except OSError:
        return ()
    key = (str(resolved), mtime)
    known = _CACHE.get(key)
    if known is not None:
        return known

    raw_data = json.loads(resolved.read_text(encoding="utf-8"))
    schema = int(raw_data.get("schema", 0))
    if schema > SCHEMA:
        raise ValueError(
            _t("model manifest in schema {schema}, known up to {known} - "
               "please update Retina").format(schema=schema, known=SCHEMA))
    fields = set(ModelSpec.__dataclass_fields__)
    specs = tuple(
        ModelSpec(**{k: v for k, v in entry.items() if k in fields})
        for entry in raw_data.get("models", ())
    )
    _CACHE[key] = specs
    return specs


def catalog() -> list[ModelSpec]:
    """Everything usable: what was found on the machine **then** the manifest.

    The order matters, and it is a rule: a model **discovered** locally (a GraXpert install)
    takes precedence over its namesake in the manifest. Both carry the same `id`
    (``graxpert-denoise-3.0.2``); by putting discovery first and deduplicating by id,
    ``spec()`` returns the entry with a **local path** — hence nothing to re-download when the
    file is already there. Without that, the manifest entry (which has a URL) would win and we
    would re-download hundreds of megabytes already present.
    """
    seen: set[str] = set()
    tout: list[ModelSpec] = []
    for definition in discover_local() + list(load_manifest()):
        if definition.id in seen:
            continue
        seen.add(definition.id)
        tout.append(definition)
    return tout


def available(task: str | None = None) -> list[ModelSpec]:
    """Usable models, filtered by task."""
    return [m for m in catalog() if task is None or m.task == task]


def spec(model_id: str) -> ModelSpec:
    tout = catalog()
    for m in tout:
        if m.id == model_id:
            return m
    connus = ", ".join(m.id for m in tout) or _t("none")
    raise KeyError(_t("unknown model: {id!r} (available: {known})")
                   .format(id=model_id, known=connus))


def _version_key(version: str) -> list[tuple[int, object]]:
    """Order "3.0.2"-style versions without depending on ``packaging``.

    A numeric segment compares as a number (``10`` after ``9``, not before); a non-numeric
    segment — an exotic local version — sorts after, in text order.
    """
    key: list[tuple[int, object]] = []
    for segment in str(version).split("."):
        key.append((0, int(segment)) if segment.isdigit() else (1, segment))
    return key


def latest_for_task(task: str) -> ModelSpec | None:
    """The most recent model for a task, or ``None`` if none is available.

    This is what a process with no explicit choice settles on: "the latest", determined on the
    version. Since a **local** model and a manifest one with the same id have already been
    merged by :func:`catalog`, there is no duplicate to arbitrate here.
    """
    candidates = available(task)
    if not candidates:
        return None
    return max(candidates, key=lambda m: _version_key(m.version))


def choices_for_tasks(tasks) -> tuple[str, ...]:
    """The drop-down of a model selector: ``latest`` then the catalog ids."""
    ids = [m.id for task in tasks for m in available(task)]
    return (LATEST, *ids)


def resolve(model_id: str, model: str, task: str) -> tuple[str, str, str]:
    """The model to use, as ``(path, name, version)``. Shared by every AI process — it is
    the single definition of the priority.

    Order: an explicitly chosen ``model_id`` (downloaded if needed), then a ``model`` (a
    supplied path), then the most recent for the task. The user's conscious choice comes before
    the automatic default.
    """
    import os

    if model_id and model_id != LATEST:
        definition = spec(model_id)
        return str(ensure(model_id)), definition.name, definition.version
    if model:
        resolved = os.path.expanduser(str(model))
        if not os.path.exists(resolved):
            raise ValueError(_t("model not found: {path}").format(path=resolved))
        return resolved, os.path.basename(resolved), ""
    definition = latest_for_task(task)
    if definition is None:
        raise ValueError(
            _t("no model available for task '{task}'. Install GraXpert, check your "
               "connection, or set 'model' (a local .onnx).").format(task=task))
    return str(ensure(definition.id)), definition.name, definition.version


def model_path(model_id: str) -> Path:
    """Where this model lives once downloaded."""
    return Path(cache_path("models", f"{model_id}.onnx"))


def is_downloaded(model_id: str) -> bool:
    definition = next((m for m in catalog() if m.id == model_id), None)
    if definition is not None and definition.path:
        return Path(definition.path).is_file()
    resolved = model_path(model_id)
    return resolved.exists() and resolved.stat().st_size > 0


def sha256_of(path: str | os.PathLike) -> str:
    """Fingerprint of a file, read in blocks — this is what enters the history."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def download(model_id: str, *, force: bool = False) -> Path:
    """Download the model and verify its fingerprint. Returns the local path.

    Progress and cancellation go through the current thread's
    :class:`~retina.process.progress.ProgressMonitor`, as for a process: inside a job, the bar
    and the "Cancel" button work with nothing further to wire up.

    Writing happens into a ``.part`` renamed at the end: a network outage never leaves a
    truncated model that would pass for valid on the next launch.
    """
    from ..process import context

    definition = spec(model_id)
    target = model_path(model_id)
    if target.exists() and not force:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)

    monitor = context.get_monitor()
    partial = target.with_suffix(target.suffix + ".part")
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
                    # `report` performs the cancellation check itself: nothing more to set.
                    monitor.report(lus / total if total else None,
                                    f"{definition.label} — {lus // (1 << 20)} MiB")
        checksum = digest.hexdigest()
        if definition.sha256 and checksum != definition.sha256:
            raise ValueError(
                _t("wrong fingerprint for model {id!r}: expected {expected}, got {got}. "
                   "File discarded.").format(id=model_id, expected=definition.sha256,
                                             got=checksum))
        partial.replace(target)
    finally:
        # This also holds for cancellation: an abandoned `.part` would be mistaken for a
        # download in progress by the next pass.
        partial.unlink(missing_ok=True)

    _notify(_t("{label} downloaded").format(label=definition.label), "info")
    return target


def ensure(model_id: str) -> Path:
    """Local path of the model, downloaded on demand if it is missing.

    A model **discovered** on the machine is returned where it is: copying it into our cache
    would duplicate hundreds of megabytes for nothing, and would let the two copies diverge at
    the first GraXpert update.
    """
    definition = next((m for m in catalog() if m.id == model_id), None)
    if definition is not None and definition.path:
        resolved = Path(definition.path)
        if not resolved.is_file():
            # A race guard, and nothing else: since discovery is redone on every call, an
            # uninstalled model has already left the catalog. All that remains is the case
            # where GraXpert updates itself while a job is running.
            raise ValueError(
                _t("model {id!r}: the file has vanished ({path}). "
                   "Was GraXpert updated during processing?").format(id=model_id,
                                                                    path=resolved))
        return resolved
    if is_downloaded(model_id):
        return model_path(model_id)
    return download(model_id)


def _notify(message: str, kind: str) -> None:
    """Log to the notification center, if an application is there to hear it."""
    from ..process import context

    try:
        app = context.get_application()
        if app is not None:
            app.notify(message, kind=kind, source="retina.ai")
    except Exception:  # headless without an application, or no center: of no consequence
        pass
