"""User session — recents, "reopen the previous one", and the interface language.

A small JSON in the configuration folder, next to the library and the perspectives. It is
neither a project nor an interface preference: it is what the application knows about the
user **between** two sessions.

Three choices not to undo:

* **paths are resolved** (``Path.resolve``) before entering the list — otherwise
  ``./m31.fits`` and ``/data/m31.fits`` would appear twice, and clicking the first would
  depend on the server's current directory, which means nothing to the user;
* **reading is tolerant**: a truncated file (an abrupt stop during the write) returns an
  empty session, never an exception. Losing a list of recents is harmless; refusing to start
  because of it would be absurd;
* **automatic reopening is disabled by default.** A project embeds every history state of
  every view: writing it at the moment the user closes the application can take time and
  space. A feature that slows down closing without being asked for is an unpleasant
  surprise; the welcome screen, for its part, offers to reopen the previous session in one
  click.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .i18n import translate as _t
from .paths import config_path

#: Length of both recents lists. Ten: beyond that, a drop-down menu becomes a search, and
#: what one should open is the file explorer.
DEFAULT_LIMIT = 10

SESSION_VERSION = 1


class SessionStore:
    """The ``session.json`` file in the configuration folder."""

    def __init__(self, path: Path | None = None, limit: int = DEFAULT_LIMIT) -> None:
        self._path = Path(path) if path is not None else config_path("session.json")
        self._limit = int(limit)
        #: GUI hook: called after any mutation (the client re-reads its recents).
        self.on_changed: Callable[[], None] | None = None

    # --- reading / writing ----------------------------------------------------
    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        data["version"] = SESSION_VERSION
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".json.part")
        try:
            temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temporary.replace(self._path)
        except OSError:
            # Do not fail a file opening because the recents list could not be written
            # (full disk, read-only folder).
            temporary.unlink(missing_ok=True)
            return
        if self.on_changed is not None:
            self.on_changed()

    # --- recents --------------------------------------------------------------
    def recent_files(self) -> list[str]:
        return list(self._read().get("recent_files", []))

    def recent_projects(self) -> list[str]:
        return list(self._read().get("recent_projects", []))

    def add_recent_file(self, path: str) -> None:
        self._add("recent_files", path)

    def add_recent_project(self, path: str) -> None:
        self._add("recent_projects", path)

    def _add(self, key: str, path: str) -> None:
        try:
            resolved = str(Path(path).expanduser().resolve())
        except (OSError, ValueError):
            resolved = str(path)
        data = self._read()
        kept = [p for p in data.get(key, []) if p != resolved]
        data[key] = [resolved, *kept][: self._limit]
        self._write(data)

    def forget(self, path: str) -> None:
        """Remove a path from both lists — a deleted file has no business being there."""
        data = self._read()
        change = False
        for key in ("recent_files", "recent_projects"):
            kept = [p for p in data.get(key, []) if p != path]
            if kept != data.get(key, []):
                data[key] = kept
                change = True
        if change:
            self._write(data)

    # --- automatic reopening --------------------------------------------------
    def reopen_enabled(self) -> bool:
        return bool(self._read().get("reopen", False))

    def set_reopen(self, enabled: bool) -> None:
        data = self._read()
        data["reopen"] = bool(enabled)
        self._write(data)

    # --- interface language ----------------------------------------------------
    def language(self) -> str | None:
        """Language chosen explicitly, or ``None`` for "follow the system"."""
        value = self._read().get("language")
        return value if isinstance(value, str) and value else None

    def set_language(self, language: str | None) -> None:
        """Set (or clear, with ``None``) the explicit language choice.

        Invalidates the memoized resolution: without that, the server would keep translating
        into the old language until it restarted, even though the client has already reloaded
        into the new one.
        """
        from . import i18n

        data = self._read()
        if language is None:
            data.pop("language", None)
        else:
            normalisee = i18n.normalize(language)
            if normalisee is None:
                raise ValueError(
                    _t("unknown language: {language!r} (expected {expected} or None)")
                    .format(language=language, expected=", ".join(i18n.LANGUAGES))
                )
            data["language"] = normalisee
        self._write(data)
        i18n.invalidate()

    def autosession_path(self) -> str:
        """Implicit project written on close when automatic reopening is enabled."""
        from .io.project import PROJECT_SUFFIX

        return str(config_path(f"autosession{PROJECT_SUFFIX}"))

    def has_autosession(self) -> bool:
        return Path(self.autosession_path()).exists()

    # --- full state (the server's hello, the welcome screen) ------------------
    def state(self) -> dict:
        from . import i18n

        data = self._read()
        return {
            "recent_files": list(data.get("recent_files", [])),
            "recent_projects": list(data.get("recent_projects", [])),
            "reopen": bool(data.get("reopen", False)),
            "has_autosession": self.has_autosession(),
            # Two distinct fields: what the user chose (`None` = automatic) and what is
            # actually served. The client needs both — the first to tick the right menu
            # entry, the second to know which language it must display in.
            "language": self.language(),
            "effective_language": i18n.effective_language(),
        }

    def __repr__(self) -> str:
        return f"SessionStore({str(self._path)!r})"
