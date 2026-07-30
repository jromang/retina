"""Retina project format — one ``.retina`` file, a whole session's state inside it.

Close the application and reopen it finding its windows, its previews, its masks, its STFs,
and **the whole history of every view** — hence undo and redo intact. The established way of
doing this is to embed the swap files inside the project; we take the principle, not the
format.

# Why HDF5, and a single file

A project is a **document**: one copies it, moves it, sends it. A folder of a thousand small
files (what zarr in directory-store mode would give) is a pain to handle and breaks on the
first incomplete transfer. HDF5 gives a single file, chunked, compressed, partially
readable — and readable with any HDF5 tool should Retina ever be gone.

Structure ::

    /                attrs: format, version, saved_at
    /manifest        str dataset: JSON — everything non-pixel
    /documents       str dataset: JSON — the shell's opaque blob (absent if none)
    /arrays/aNNNNNN  (H, W, C) float32, chunked in row bands, gzip+shuffle+fletcher32

The manifest is a **dataset**, not attributes scattered around: HDF5 attributes top out
around 64 KB, and a single JSON versions, reads back tolerantly, and stays readable by eye
with ``h5dump``. The pixel datasets carry no metadata at all — one single source of truth.

The filter is **gzip level 1 + shuffle**, not an exotic codec: shuffle is what makes astro
float32 compressible (it groups the bytes of equal significance), gzip is in the HDF5 core
hence readable everywhere, and level 1 keeps writing fast. An external filter (zstd through
``hdf5plugin``) would make the file unreadable without the plugin installed — unacceptable
for a document format.

# Deduplication

The same pixels appear several times in a session: a view's current image **is** that of its
current history entry, a mask set from a view **is** its array. We therefore index by object
identity (``id()``), keeping a strong reference for the duration of the write — without it, a
freed array would make its ``id()`` reusable and the table would designate two different
contents under the same key. On read-back, the reverse table restores the **object sharing**:
``win.mask.data is view.image.data`` survives the round trip.

# What the format does not carry, and why

The widget geometry (``vw``/``vh``/``dpr``): it describes today's screen. The state of
``Blink``: the window is persisted, the file sequence one was stepping through is not — it is
a gesture, not a document.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

import numpy as np

from ..i18n import translate as _t
from ..model.image import Image
from ..model.stf import STF
from ..model.view import HistoryEntry, View
from ..model.window import ImageWindow

#: File suffix. A single file, not a bundle: see the module header.
PROJECT_SUFFIX = ".retina"

#: Format version. Unknown major → explicit refusal; unknown keys → ignored.
FORMAT_VERSION = 1

_FORMAT_TAG = "retina-project"

#: Chunk height. Large enough for gzip to have material, small enough that writing a
#: 100 Mpx exposure does not call for a giant buffer.
_CHUNK_ROWS = 256


def _require_h5py():
    """Lazy import — ``import retina`` must not pull in h5py (headless parity)."""
    try:
        import h5py
    except ModuleNotFoundError as exc:  # pragma: no cover — install dependent
        raise RuntimeError(
            _t("Retina projects require h5py: pip install 'retina[project]'")
        ) from exc
    return h5py


# --- opening report --------------------------------------------------------------------

@dataclass
class ProjectReport:
    """What opening a project found — and what was wrong.

    The three problem lists are returned **at opening time**, not on the first replay: a
    project reopened six months later must say right away which of its scripts have moved,
    rather than failing in the middle of a recipe.
    """

    path: str = ""
    windows: list[str] = field(default_factory=list)
    #: ``process_id`` replaced by an :class:`~retina.process.unknown.UnknownProcess`.
    unknown_processes: list[str] = field(default_factory=list)
    #: ``Script`` instances whose file has disappeared.
    scripts_missing: list[str] = field(default_factory=list)
    #: ``Script`` instances whose content has changed since saving (SHA-256).
    scripts_changed: list[str] = field(default_factory=list)
    #: The shell's opaque blob (tabs, buffers, transcript) — never interpreted here.
    documents: object | None = None

    def to_dict(self) -> dict:
        """Network form — **without** ``documents``, which travels on its own channel."""
        return {
            "path": self.path,
            "windows": list(self.windows),
            "unknown_processes": list(self.unknown_processes),
            "scripts_missing": list(self.scripts_missing),
            "scripts_changed": list(self.scripts_changed),
        }


# --- array store -----------------------------------------------------------------------

class _ArrayStore:
    """Key ↔ ndarray table, deduplicated by object identity.

    The strong reference is not a stylistic precaution: without it, an intermediate array
    freed during the write would make its ``id()`` reassignable, and two different contents
    would share a key — a silent corruption.
    """

    def __init__(self) -> None:
        self._keys: dict[int, str] = {}
        self._order: list[tuple[str, np.ndarray]] = []
        self._alive: list[np.ndarray] = []

    def key_for(self, data: np.ndarray) -> str:
        existing = self._keys.get(id(data))
        if existing is not None:
            return existing
        key = f"a{len(self._order):06d}"
        self._keys[id(data)] = key
        self._alive.append(data)
        self._order.append((key, data))
        return key

    def __len__(self) -> int:
        return len(self._order)

    def items(self):
        return list(self._order)

    def nbytes(self) -> int:
        return sum(int(a.nbytes) for _, a in self._order)


# --- FITS keywords ---------------------------------------------------------------------

def _keyword_triplets(keywords: dict) -> list[list]:
    """``{key: value}`` → ``[[key, value, type], …]``, insertion order preserved.

    A list and not a dict: ``COMMENT``/``HISTORY`` legitimately repeat in a FITS header, and
    a dict would crush them. The third field names the type because
    ``astropy.io.fits.card.Undefined`` — a keyword present *without a value*, a common case —
    has no JSON representation at all: making it ``null`` without saying so would read it
    back as an empty string.
    """
    triplets: list[list] = []
    for key, value in keywords.items():
        if isinstance(value, bool):
            triplets.append([str(key), bool(value), "bool"])
        elif isinstance(value, (int, np.integer)):
            triplets.append([str(key), int(value), "int"])
        elif isinstance(value, (float, np.floating)):
            triplets.append([str(key), float(value), "float"])
        elif isinstance(value, str):
            triplets.append([str(key), value, "str"])
        elif type(value).__name__ == "Undefined":
            triplets.append([str(key), None, "undefined"])
        else:
            # Honest fallback: keep a readable trace rather than throw the keyword away.
            triplets.append([str(key), repr(value), "repr"])
    return triplets


def _keywords_from_triplets(triplets) -> dict:
    keywords: dict[str, object] = {}
    for entry in triplets:
        try:
            key, value, kind = entry
        except (TypeError, ValueError):
            continue
        if kind == "undefined":
            from astropy.io import fits

            keywords[key] = fits.card.Undefined()
        else:
            keywords[key] = value
    return keywords


# --- WCS -------------------------------------------------------------------------------

def _wcs_to_text(wcs) -> str | None:
    """The WCS FITS header, as text. ``relax=True`` keeps the extended conventions
    (SIP, distortions) a plate-solve produces and that a ``dict(to_header())`` would lose."""
    if wcs is None:
        return None
    try:
        return wcs.to_header(relax=True).tostring(sep="\n", endcard=True, padding=False)
    except Exception:
        return None


def _wcs_from_text(text: str | None):
    if not text:
        return None
    try:
        from astropy.io import fits
        from astropy.wcs import WCS

        return WCS(fits.Header.fromstring(text, sep="\n"))
    except Exception:
        return None


# --- view serialization ----------------------------------------------------------------

def _view_to_dict(view: View, arrays: _ArrayStore) -> dict:
    entries = []
    for entry in view.history_entries():
        process = entry.process
        raw_data = {
            "label": entry.label,
            "image": arrays.key_for(entry.image.data),
            "process": process.to_dict() if process is not None else None,
        }
        # Written only when a step actually carried a mask: most do not, and a `null` key
        # everywhere would inflate the manifest for nothing. Symmetric with reading, which is
        # tolerant by default — a project written before this feature reads back intact.
        if entry.mask_id is not None:
            raw_data["mask"] = entry.mask_id
            raw_data["mask_inverted"] = bool(entry.mask_inverted)
        entries.append(raw_data)
    data: dict[str, Any] = {
        "id": view.id,
        "stf_enabled": bool(view.stf_enabled),
        "stf": None if view.stf is None else view.stf.to_dict(),
        "history": {"index": view.history_index, "entries": entries},
    }
    # Written only when present: a project saved before view properties existed reads back
    # unchanged, and most views carry none.
    if view.properties:
        data["properties"] = view.properties
    if view.is_preview:
        data["rect"] = list(view.rect)
        data["volatile"] = bool(view.volatile)
    return data


def _history_from_dict(data: dict, arrays: dict[str, Image],
                       report: ProjectReport) -> tuple[list[HistoryEntry], int]:
    from ..process.unknown import UnknownProcess, process_from_dict

    entries: list[HistoryEntry] = []
    for raw_data in data.get("entries", ()):
        image = arrays[raw_data["image"]]
        process = None
        if raw_data.get("process") is not None:
            process = process_from_dict(raw_data["process"])
            if (isinstance(process, UnknownProcess)
                    and process.process_id not in report.unknown_processes):
                report.unknown_processes.append(process.process_id)
        entries.append(HistoryEntry(
            raw_data.get("label", "process"), image, process,
            raw_data.get("mask"), bool(raw_data.get("mask_inverted", False))))
    index = int(data.get("index", len(entries) - 1))
    index = max(0, min(index, len(entries) - 1)) if entries else 0
    return entries, index


def _apply_view_dict(view: View, data: dict, arrays: dict[str, Image],
                     report: ProjectReport) -> None:
    entries, index = _history_from_dict(data.get("history", {}), arrays, report)
    if entries:
        view.restore_history(entries, index)
    view.stf_enabled = bool(data.get("stf_enabled", True))
    stf = data.get("stf")
    view.stf = None if stf is None else STF.from_dict(stf)
    view.load_properties(data.get("properties") or {})


# --- window serialization --------------------------------------------------------------

def _window_to_dict(win: ImageWindow, arrays: _ArrayStore) -> dict:
    data: dict[str, Any] = {
        "id": win.id,
        "file_path": win.file_path,
        "is_modified": bool(win.is_modified),
        "keywords": _keyword_triplets(win.keywords),
        "wcs": _wcs_to_text(win.wcs),
        "mask": None if win.mask is None else {
            "array": arrays.key_for(win.mask.data),
            "enabled": bool(win.mask_enabled),
            "inverted": bool(win.mask_inverted),
            # The id of the source view, without which a history step replayed after
            # reopening would no longer know which mask it had used.
            "source": win.mask_source_id,
        },
        "current_view": win.current_view.id,
        "viewport": win.viewport.to_dict(),
        "main_view": _view_to_dict(win.main_view, arrays),
        "previews": [_view_to_dict(pv, arrays) for pv in win.previews],
    }
    # A *dynamic* attribute, set by AssignICCProfile and absent from `ImageWindow.__init__`:
    # serializing it unconditionally would write `None` for every window and give the
    # impression that a profile had been removed.
    profile = getattr(win, "icc_profile", None)
    if profile is not None:
        data["icc_profile"] = profile
    return data


def _window_from_dict(data: dict, arrays: dict[str, Image],
                      report: ProjectReport) -> ImageWindow:
    """Rebuild a **detached** window — it enters the application only at commit time.

    The order of the five stages is not indifferent:

    1. the window and the main view's history first, because the *base* of a volatile
       preview is that view's current state;
    2. the metadata and the mask;
    3. the previews, each with its own history;
    4. the current view — which requires the previews to exist;
    5. the viewport **last**: ``set_current_view`` calls ``set_image_size``, and setting the
       camera before would get overwritten.
    """
    main_view = data.get("main_view", {})
    entries, index = _history_from_dict(main_view.get("history", {}), arrays, report)
    if not entries:
        raise ValueError(
            _t("Window {id!r} has no image state.").format(id=data.get("id"))
        )
    win = ImageWindow(entries[index].image, window_id=data.get("id", ""),
                      file_path=data.get("file_path"))
    _apply_view_dict(win.main_view, main_view, arrays, report)

    win.keywords = _keywords_from_triplets(data.get("keywords", ()))
    win.wcs = _wcs_from_text(data.get("wcs"))
    win.is_modified = bool(data.get("is_modified", False))
    if "icc_profile" in data:
        win.icc_profile = data["icc_profile"]
    mask = data.get("mask")
    if mask is not None:
        win.set_mask(arrays[mask["array"]], inverted=bool(mask.get("inverted", False)),
                     source_id=mask.get("source"))
        win.mask_enabled = bool(mask.get("enabled", True))

    for raw_data in data.get("previews", ()):
        x0, y0, x1, y1 = raw_data.get("rect", (0, 0, 1, 1))
        pv = win.create_preview(x0, y0, x1, y1, preview_id=raw_data.get("id", ""))
        _apply_view_dict(pv, raw_data, arrays, report)
        # After the history: a true `volatile` would make the preview be re-sliced from the
        # base on the first `begin_process`, which is precisely the behavior to restore —
        # but only once its original state is back in place.
        pv.volatile = bool(raw_data.get("volatile", True))

    current = data.get("current_view")
    if current and current != win.id:
        pv = win.preview_by_id(current)
        if pv is not None:
            win.set_current_view(pv)
    win.viewport.apply_dict(data.get("viewport", {}))
    return win


# --- scripts: what has moved since saving ----------------------------------------------

def _audit_scripts(windows: list[ImageWindow], report: ProjectReport) -> None:
    """Report the ``Script`` instances whose file has disappeared or changed.

    The ``Script`` process already knows how to compare its digest — but only **on replay**,
    by printing a line into the console. A project must say so at opening time: that is when
    the user can still go and look for the file.
    """
    from ..processes.script import file_digest

    views: list[View] = []
    for win in windows:
        views.append(win.main_view)
        views.extend(win.previews)
    for view in views:
        for entry in view.history_entries():
            process = entry.process
            if process is None or getattr(process, "process_id", "") != "Script":
                continue
            path = str(getattr(process, "path", "") or "")
            if not path:
                continue
            if not os.path.exists(path):
                if path not in report.scripts_missing:
                    report.scripts_missing.append(path)
                continue
            digest = getattr(process, "digest", "")
            if (digest and file_digest(path) != digest
                    and path not in report.scripts_changed):
                report.scripts_changed.append(path)


# --- public API ------------------------------------------------------------------------

def estimate_size(app) -> int:
    """Bytes of **unique** pixels in a session, before compression.

    A useful upper bound: it is what the disk would see without dedup or gzip. Meant to warn
    ahead of three minutes of writing, not to promise a file size.
    """
    arrays = _ArrayStore()
    for win in app.windows:
        _window_to_dict(win, arrays)
    return arrays.nbytes()


def save_project(app, path: str, *, documents: object | None = None) -> dict:
    """Write the whole session into ``path``. Returns a summary of what was written.

    The write is **atomic** (neighboring temporary file then ``os.replace``): an
    interruption, a cancellation or a full disk never leave a truncated ``.retina`` that a
    later opening would believe valid.
    """
    from ..pipeline.cache import save_atomic
    from ..process.context import get_monitor

    h5py = _require_h5py()
    if not path.endswith(PROJECT_SUFFIX):
        path += PROJECT_SUFFIX

    arrays = _ArrayStore()
    manifest = {
        "version": FORMAT_VERSION,
        "active_window": app.active_window.id if app.active_window is not None else None,
        "linked_viewports": app.linked_viewports(),
        "window_counter": ImageWindow._counter,
        "windows": [_window_to_dict(win, arrays) for win in app.windows],
    }

    monitor = get_monitor()
    total = max(1, len(arrays))

    def _write(target: str) -> None:
        with h5py.File(target, "w") as file:
            file.attrs["format"] = _FORMAT_TAG
            file.attrs["version"] = FORMAT_VERSION
            file.attrs["saved_at"] = _now_iso()
            group = file.create_group("arrays")
            for rank, (key, array) in enumerate(arrays.items()):
                if monitor is not None:
                    monitor.report(rank / total, f"writing pixels ({rank + 1}/{total})")
                _write_array(group, key, array)
            file.create_dataset(
                "manifest", data=json.dumps(manifest), dtype=h5py.string_dtype("utf-8"))
            if documents is not None:
                file.create_dataset(
                    "documents", data=json.dumps(documents),
                    dtype=h5py.string_dtype("utf-8"))
        if monitor is not None:
            monitor.report(1.0, "project written")

    save_atomic(path, _write)
    return {
        "path": path,
        "windows": len(app.windows),
        "arrays": len(arrays),
        "bytes": os.path.getsize(path),
    }


def _write_array(group, key: str, array: np.ndarray) -> None:
    """A dataset chunked in row bands, compressed, with a checksum.

    ``write_direct`` avoids the intermediate buffer that ``group[key] = array`` would build:
    on a 100 Mpx color exposure, that is 1.2 GB of copying saved.
    """
    array = np.ascontiguousarray(array, dtype=np.float32)
    h, w = array.shape[0], array.shape[1]
    c = array.shape[2] if array.ndim > 2 else 1
    dataset = group.create_dataset(
        key,
        shape=array.shape,
        dtype=np.float32,
        chunks=(min(_CHUNK_ROWS, h) or 1, w or 1, c or 1),
        compression="gzip",
        compression_opts=1,
        shuffle=True,
        fletcher32=True,
    )
    dataset.write_direct(array)


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def _open_and_check(path: str):
    """Open the file and check the format; returns ``(file, manifest)``."""
    h5py = _require_h5py()
    file = h5py.File(path, "r")
    try:
        if file.attrs.get("format") != _FORMAT_TAG:
            raise ValueError(_t("{path} is not a Retina project.").format(path=path))
        version = int(file.attrs.get("version", 0))
        if version > FORMAT_VERSION:
            raise ValueError(
                _t(
                    "Project is version {version}, this copy of Retina reads up to "
                    "{max_version}. Update Retina to open it."
                ).format(version=version, max_version=FORMAT_VERSION)
            )
        manifest = json.loads(_read_text(file, "manifest") or "{}")
    except BaseException:
        file.close()
        raise
    return file, manifest


def _read_text(file, name: str) -> str | None:
    if name not in file:
        return None
    raw_data = file[name][()]
    return raw_data.decode("utf-8") if isinstance(raw_data, bytes) else str(raw_data)


def read_documents(path: str) -> object | None:
    """Read the shell's blob alone, without touching the windows or loading a single pixel."""
    file, _ = _open_and_check(path)
    with file:
        text = _read_text(file, "documents")
    return None if text is None else json.loads(text)


def load_project(app, path: str) -> ProjectReport:
    """Replace ``app``'s session with the project's.

    **Transactional**: everything is built off to the side, and the application is touched
    only at the final commit. A cancellation or a damaged file halfway through therefore
    leaves the session in place, rather than a half project to be untangled by hand.
    """
    from ..process.context import get_monitor

    monitor = get_monitor()
    file, manifest = _open_and_check(path)
    report = ProjectReport(path=path)
    with file:
        group = file.get("arrays", {})
        keys = list(group.keys())
        total = max(1, len(keys))
        arrays: dict[str, Image] = {}
        for rank, key in enumerate(keys):
            if monitor is not None:
                monitor.report(rank / total, f"reading pixels ({rank + 1}/{total})")
            arrays[key] = Image(np.asarray(group[key][()], dtype=np.float32))
        text = _read_text(file, "documents")
        report.documents = None if text is None else json.loads(text)

    windows = [_window_from_dict(raw_data, arrays, report)
                for raw_data in manifest.get("windows", ())]

    # **Global** uniqueness of view identifiers: it is the pixel addressing scheme
    # (`/api/pixels/<id>.f16`, generation keys, `app.view(id)`). Two homonymous views make
    # the generation oscillate and render the second one undisplayable — we refuse before
    # touching the application, not halfway through.
    _check_unique_ids(windows)

    # --- commit: from here on, nothing more can fail ---
    app.windows.clear()
    app.windows.extend(windows)
    app._active = None
    active = manifest.get("active_window")
    for win in windows:
        if win.id == active:
            app._active = win
    if app._active is None and windows:
        app._active = windows[-1]
    restored = {win.id for win in windows}
    app._linked = {wid for wid in manifest.get("linked_viewports", ()) if wid in restored}
    ImageWindow._counter = max(int(manifest.get("window_counter", 0)),
                               _highest_index(windows))
    app._notify_windows()

    report.windows = [win.id for win in windows]
    _audit_scripts(windows, report)
    if monitor is not None:
        monitor.report(1.0, "project opened")
    return report


def _check_unique_ids(windows: list[ImageWindow]) -> None:
    seen: set[str] = set()
    collisions: list[str] = []
    for win in windows:
        for view_id in [win.id] + [pv.id for pv in win.previews]:
            if view_id in seen:
                collisions.append(view_id)
            seen.add(view_id)
    if collisions:
        raise ValueError(
            _t("Duplicate view identifiers in the project: {ids}").format(
                ids=", ".join(sorted(set(collisions)))
            )
        )


def _highest_index(windows: list[ImageWindow]) -> int:
    """Largest ``N`` among the ids of the form ``ImageNN``.

    ``ImageWindow._counter`` is a **class** variable: without this realignment, the first
    window created after opening a project would take back an identifier already in use, and
    the pixel addressing would designate two views at once.
    """
    import re

    highest = 0
    for win in windows:
        found = re.fullmatch(r"Image(\d+)", win.id)
        if found:
            highest = max(highest, int(found.group(1)))
    return highest
