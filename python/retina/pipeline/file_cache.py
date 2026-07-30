"""Persistent per-**file** cache — the generic machinery (a FileDataCache equivalent).

Extracted from :mod:`.measure_cache` to serve a second domain: the registration stars
(:class:`StarCache`). Each domain has its JSON file under ``config_path``, its format
version, and the same key — absolute path, identity (size, mtime_ns) and settings.
The on-disk format is **that of the measurement cache v2, unchanged**: ``MeasureCache``
inherits from here without invalidating a single existing entry (the key does not include
the domain, it is the file name that separates the domains).

Accepted limitations (see measure_cache.py): identity = size/date, not a hash; two
simultaneous writes, the last one wins — a lost cache rebuilds itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from ..paths import config_path
from . import cache as _cache

#: age beyond which an unused entry is forgotten. Thirty days cover a season of work on the
#: same object without letting the file grow indefinitely.
DEFAULT_MAX_AGE_DAYS = 30


def _default_root() -> Path:
    """Same convention as the library and the perspectives (cf. tests/test_paths.py)."""
    return config_path("measure-cache")


def _identity(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


class FileDataCache:
    """Already computed payloads, indexed by file **and** by settings."""

    #: name of the JSON file — one per domain, under the same config folder
    filename = "cache.json"
    #: format version; a change in the payload must invalidate the domain
    version = "1"

    def __init__(self, root: Path | None = None,
                 max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> None:
        self._root = Path(root) if root is not None else _default_root()
        self._max_age = float(max_age_days) * 86400.0
        self._entries: dict[str, dict] | None = None
        self._dirty = False

    # --- key -------------------------------------------------------------------
    @classmethod
    def key(cls, path: str, settings: dict) -> str:
        """Identity of an entry: the file as it is, and how it is processed."""
        size = _identity(path)
        charge = {
            "version": cls.version,
            "path": os.path.abspath(path),
            "size": None if size is None else size[0],
            "mtime_ns": None if size is None else size[1],
            "settings": settings,
        }
        blob = json.dumps(charge, sort_keys=True, ensure_ascii=False, default=repr)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # --- access ----------------------------------------------------------------
    @property
    def path(self) -> Path:
        return self._root / self.filename

    def _load(self) -> dict[str, dict]:
        if self._entries is not None:
            return self._entries
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        entries = data.get("entries", {}) if isinstance(data, dict) else {}
        # Purge on read rather than on write: it is the only moment when the whole file is
        # already in hand, and a stale entry must not be served again.
        limit = time.time() - self._max_age
        kept = {key: e for key, e in entries.items()
                 if isinstance(e, dict) and float(e.get("last_used", 0)) >= limit}
        self._dirty = len(kept) != len(entries)
        self._entries = kept
        return self._entries

    def get(self, path: str, settings: dict) -> dict | None:
        """Payload already computed for this file and these settings, or ``None``."""
        if _identity(path) is None:
            return None
        entries = self._load()
        entry = entries.get(self.key(path, settings))
        if entry is None:
            return None
        entry["last_used"] = time.time()
        self._dirty = True
        # Field named "measure" so as to stay readable by the existing v2 caches — it is a
        # historical name, the payload is whatever the domain stores in it.
        measure = entry.get("measure")
        # A copy: the caller completes its version without polluting the cached entry.
        return dict(measure) if isinstance(measure, dict) else None

    def put(self, path: str, settings: dict, payload: dict) -> None:
        entries = self._load()
        entries[self.key(path, settings)] = {
            "path": os.path.abspath(path),
            "last_used": time.time(),
            "measure": dict(payload),
        }
        self._dirty = True

    def flush(self) -> None:
        """Writes the cache if it has changed. Atomic: never a half-written file."""
        if not self._dirty or self._entries is None:
            return
        self._root.mkdir(parents=True, exist_ok=True)
        charge = {"version": self.version, "entries": self._entries}
        try:
            _cache.save_atomic(str(self.path), lambda tmp: Path(tmp).write_text(
                json.dumps(charge, ensure_ascii=False), encoding="utf-8"))
        except OSError:
            return  # a cache that cannot be written is not a processing error
        self._dirty = False

    def clear(self) -> None:
        """Forgets everything. Leaves the cache empty, on disk as in memory."""
        self._entries = {}
        self._dirty = True
        self.flush()

    def __len__(self) -> int:
        return len(self._load())

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self.path)!r}, {len(self)} entry(ies))"


class StarCache(FileDataCache):
    """Registration stars per file — saves one sep detection per frame AND per run.

    The payload is ``{"stars": [[x, y], …]}`` (≤ ``max_points`` positions sorted by flux);
    the settings carry the detector and its parameters, so that changing one of them creates
    a distinct entry rather than serving a wrong one again.
    """

    filename = "stars.json"
    version = "1"
