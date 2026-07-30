"""Preferences — the settings that depend on neither an image nor a project.

There was a path convention (:mod:`retina.paths`) and a handful of consumers, but **no
preferences object**. Concretely, a user could not choose where their temporary files went —
which, before launching a two-hundred-gigabyte run, is not a comfort detail but a matter of
trust.

# What this module is, and what it is not

It is **pure domain**: the standard library and nothing else, no dependency on the shell,
usable from a script with no server. The settings panel will be only a client of it, like the
console — ``app.preferences.set('folders.temp_dir', '/scratch')`` does exactly what the form
does, and the converse holds.

It is not ``session.json``, which keeps what the application knows about the user *between*
two sessions: recents, last session, language. The **language** and the **reopening**
therefore stay in :class:`~retina.session.SessionStore` — that is where the shell already
fetches them, and the client's language reload depends on it. They are here by
**delegation**: visible and adjustable in the same place as the rest, stored where they have
always been. A migration would have broken existing configurations for no gain.

# The schema reuses ``Parameter``

The :class:`~retina.process.base.Parameter` descriptors already describe a typed and bounded
setting, and the server knows how to project them into an auto-generated form. Reusing them
here means a free preferences panel, consistent with the rest — rather than a second
meta-model that would diverge on the first addition. The only thing missing was the
**group**, which has no place on a process parameter; it therefore lives in
:class:`PreferenceGroup`, alongside.

# Only non-default values are written

A ``preferences.json`` that contains only what the user changed reads back correctly when a
default evolves, and is readable by eye. Writing the whole schema would freeze the defaults of
the day of installation.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .i18n import N_
from .i18n import translate as _t
from .paths import config_path
from .process.base import Parameter

PREFERENCES_VERSION = 1


@dataclass(frozen=True)
class PreferenceGroup:
    """A group of settings — the panel's display unit."""

    id: str          # domain identifier, never translated
    label: str       # English msgid, translated at the edge (server)
    parameters: tuple[Parameter, ...]


#: The schema. The keys are **prefixed by their group**: a flat identifier would make
#: `app.preferences.set('language', …)` ambiguous the day two groups want the same name.
SCHEMA: tuple[PreferenceGroup, ...] = (
    PreferenceGroup("folders", N_("Folders"), (
        Parameter("folders.pipeline_output_dir", "dir", "",
                  label=N_("Pipeline output folder"),
                  tooltip=N_("Empty: alongside the frames, in retina_pipeline/")),
        Parameter("folders.temp_dir", "dir", "", label=N_("Temporary files"),
                  tooltip=N_("Empty: the system temporary folder")),
    )),
    PreferenceGroup("performance", N_("Performance"), (
        Parameter("performance.max_workers", "int", 4, 1, 32,
                  label=N_("Concurrent jobs"),
                  tooltip=N_("Takes effect at next launch")),
        Parameter("performance.gpu_enabled", "bool", True, label=N_("Use the GPU when available"),
                  tooltip=N_("RETINA_GPU=0 overrides this setting")),
    )),
    PreferenceGroup("viewport", N_("Viewport defaults"), (
        Parameter("viewport.mask_display_mode", "enum", "overlay_red",
                  choices=("hidden", "overlay_red", "overlay_green", "overlay_blue",
                           "overlay_white", "overlay_black", "replace", "multiply",
                           "screen", "difference"),
                  label=N_("Mask display"),
                  tooltip=N_("Applies to newly opened windows")),
        Parameter("viewport.transparency_mode", "enum", "background_brush",
                  choices=("hide", "background_brush", "color"),
                  label=N_("Transparency display")),
        Parameter("viewport.readout_probe_size", "int", 1, 1, 15,
                  label=N_("Readout probe size (px)")),
    )),
    PreferenceGroup("session", N_("Session"), (
        Parameter("session.language", "enum", "auto", choices=("auto", "en", "fr"),
                  label=N_("Interface language")),
        Parameter("session.reopen", "bool", False,
                  label=N_("Reopen the previous session on startup")),
        Parameter("session.recent_limit", "int", 10, 1, 50, label=N_("Recent files kept")),
        # Unchecked by the tour itself, at the end or on the first "Skip". It is a setting
        # and not a hidden flag: someone who wants to see it again must be able to turn it
        # back on without editing a JSON — and the palette command exists too.
        Parameter("session.show_tour", "bool", True,
                  label=N_("Show the guided tour at startup")),
    )),
)

#: flat index, built once
_SETTINGS: dict[str, Parameter] = {
    p.id: p for group in SCHEMA for p in group.parameters
}

#: keys whose value does **not** live in ``preferences.json`` but in ``session.json``.
#: See the module docstring: this is a deliberate delegation, not an oversight.
DELEGATED = ("session.language", "session.reopen")


def parameters() -> dict[str, Parameter]:
    return dict(_SETTINGS)


class Preferences:
    """The user's settings, read from and written to ``config_dir()/preferences.json``."""

    def __init__(self, echo: Callable[[str], None] | None = None,
                 session_provider: Callable[[], Any] | None = None,
                 path: Path | None = None) -> None:
        self._echo = echo
        self._session_provider = session_provider
        self._path = Path(path) if path is not None else config_path("preferences.json")
        self._values: dict[str, Any] | None = None
        #: shell hook: called after any mutation.
        self.on_changed: Callable[[], None] | None = None
        #: effects to push outside the module when a key changes (GPU, viewport defaults).
        #: The domain stays pure: it is the ``Application`` that wires, not us that imports.
        self._appliers: dict[str, Callable[[Any], None]] = {}

    # --- persistence ----------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        if self._values is not None:
            return self._values
        try:
            raw_data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw_data = {}
        values = raw_data.get("values") if isinstance(raw_data, dict) else None
        self._values = dict(values) if isinstance(values, dict) else {}
        return self._values

    def _write(self) -> None:
        values = self._read()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".json.part")
        try:
            temporary.write_text(
                json.dumps({"version": PREFERENCES_VERSION, "values": values}, indent=2),
                encoding="utf-8")
            temporary.replace(self._path)
        except OSError:
            # A full disk must not make a setting fail: the value stays in place for the
            # current session, it simply will not survive the restart.
            temporary.unlink(missing_ok=True)

    # --- reading --------------------------------------------------------------
    def _setting(self, key: str) -> Parameter:
        param = _SETTINGS.get(key)
        if param is None:
            raise KeyError(_t("unknown preference: {key!r} (known: {known})")
                           .format(key=key, known=sorted(_SETTINGS)))
        return param

    def get(self, key: str) -> Any:
        """Effective value — the user's, or the schema's default."""
        param = self._setting(key)
        if key in DELEGATED:
            return self._from_session(key, param)
        values = self._read()
        return values.get(key, param.default)

    def all(self) -> dict[str, Any]:
        return {pref: self.get(pref) for pref in _SETTINGS}

    def describe(self) -> list[dict[str, Any]]:
        """The schema, group by group, with the current values.

        The labels stay **msgid**: translation happens at the edge (server), as for process
        parameters.
        """
        return [
            {"id": group.id, "label": group.label,
             "parameters": [{"parameter": p, "value": self.get(p.id)}
                            for p in group.parameters]}
            for group in SCHEMA
        ]

    # --- writing --------------------------------------------------------------
    def _validate(self, param: Parameter, value: Any) -> Any:
        """What ``Parameter.coerce`` does not do: bounds and membership of the choices."""
        coerced = param.coerce(value)
        if param.choices and coerced not in param.choices:
            raise ValueError(
                _t("{id}: {value!r} is outside the allowed values ({choices})")
                .format(id=param.id, value=coerced,
                        choices=", ".join(param.choices)))
        if param.type in ("int", "real"):
            if param.min is not None:
                coerced = max(coerced, type(coerced)(param.min))
            if param.max is not None:
                coerced = min(coerced, type(coerced)(param.max))
        if param.type == "dir" and isinstance(coerced, str):
            coerced = str(Path(coerced).expanduser()) if coerced.strip() else ""
        return coerced

    def set(self, key: str, value: Any) -> Any:
        """Set a preference. Returns the value kept (bounded, coerced)."""
        param = self._setting(key)
        coerced = self._validate(param, value)
        if key in DELEGATED:
            self._to_session(key, coerced)
        else:
            self._read()[key] = coerced
            self._write()
        self._after(key, coerced, f"app.preferences.set({key!r}, {coerced!r})")
        return coerced

    def reset(self, key: str | None = None) -> None:
        """Return a preference — or all of them — to its default."""
        keys = [key] if key else list(_SETTINGS)
        if key:
            self._setting(key)
        values = self._read()
        for pref in keys:
            if pref in DELEGATED:
                self._to_session(pref, _SETTINGS[pref].default)
            else:
                values.pop(pref, None)
        self._write()
        code = f"app.preferences.reset({key!r})" if key else "app.preferences.reset()"
        for pref in keys:
            self._apply_to(pref, self.get(pref))
        self._report(code)

    def _after(self, key: str, coerced: Any, code: str) -> None:
        self._apply_to(key, coerced)
        self._report(code)

    def _report(self, code: str) -> None:
        if self._echo is not None:
            self._echo(code)
        if self.on_changed is not None:
            self.on_changed()

    # --- effects --------------------------------------------------------------
    def add_applier(self, key: str, fn: Callable[[Any], None]) -> None:
        """Wire a side effect onto a key, and apply it right away."""
        self._setting(key)
        self._appliers[key] = fn
        fn(self.get(key))

    def _apply_to(self, key: str, coerced: Any) -> None:
        applier = self._appliers.get(key)
        if applier is not None:
            applier(coerced)

    # --- delegation to the session --------------------------------------------
    def _session(self):
        if self._session_provider is None:
            return None
        try:
            return self._session_provider()
        except Exception:
            return None

    def _from_session(self, key: str, param: Parameter) -> Any:
        store = self._session()
        if store is None:
            return param.default
        if key == "session.language":
            return store.language() or "auto"
        return bool(store.reopen_enabled())

    def _to_session(self, key: str, coerced: Any) -> None:
        store = self._session()
        if store is None:
            return
        if key == "session.language":
            store.set_language(None if coerced == "auto" else str(coerced))
        else:
            store.set_reopen(bool(coerced))


# --- module access, for consumers that cannot see the ``Application`` -----------------
#
# Same mechanics as ``i18n.set_preference_source``: the application registers itself, and a
# low-level module (the GPU dispatch, a process opening a temporary file) reads without ever
# importing the application layer. Without a provider, we fall back on a local instance — a
# headless script must work as is.

_source: Callable[[], Preferences] | None = None
_defaut: Preferences | None = None


def set_source(provider: Callable[[], Preferences] | None) -> None:
    global _source
    _source = provider


def current() -> Preferences:
    global _defaut
    if _source is not None:
        return _source()
    if _defaut is None:
        _defaut = Preferences()
    return _defaut


def value(key: str) -> Any:
    return current().get(key)


def temp_root() -> str | None:
    """The temporary files folder, or ``None`` for the system's.

    ``None`` too if the configured folder has disappeared: a stale setting must never make a
    run fail. That is the kind of breakage one does not connect back to its cause.
    """
    path = str(value("folders.temp_dir") or "").strip()
    if not path:
        return None
    return path if Path(path).is_dir() else None
