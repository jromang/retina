"""Application language — resolution, persisted preference, console parity.

What is checked here is not "translation works" (it is empty as long as no catalogue is
compiled, and that is the intended behaviour) but **the resolution order** and the fact that
a preference survives a restart.
"""

from __future__ import annotations

import pytest
from retina import i18n
from retina.app import Application
from retina.session import SessionStore


@pytest.fixture
def store(tmp_path):
    """A ``session.json`` of one's own, wired in as the preference ``retina.i18n`` sees."""
    session_store = SessionStore(tmp_path / "session.json")
    i18n.set_preference_source(session_store.language)
    return session_store


@pytest.fixture
def posix_locale(monkeypatch):
    """Force the POSIX branch of :func:`retina.i18n.system_language`.

    Without it, the tests that set ``$LANG`` check nothing under Windows: there the function
    queries ``GetUserDefaultLocaleName`` and ignores the environment, so they were reading the
    machine's language — green on a French Windows, red on an English one, and never for the
    reason they claim. We pin the platform so the resolution order is checked the same way
    everywhere.
    """
    monkeypatch.setattr("sys.platform", "linux")


# --- normalisation ------------------------------------------------------------------------

@pytest.mark.parametrize(
    "label_text, expected",
    [
        ("fr", "fr"),
        ("fr-FR", "fr"),
        ("fr_FR.UTF-8", "fr"),
        ("fr_BE.UTF-8@euro", "fr"),
        ("EN-us", "en"),
        # A language we do not serve must **not** be retained: better to fall through to the
        # next source than to display a half-translated interface.
        ("de-DE", None),
        ("C", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_label_normalisation(label_text, expected):
    assert i18n.normalize(label_text) == expected


# --- resolution order ---------------------------------------------------------------------

def test_the_environment_variable_beats_the_preference(store, monkeypatch):
    store.set_language("fr")
    monkeypatch.setenv(i18n.ENV_VAR, "en")
    i18n.invalidate()
    assert i18n.effective_language() == "en"


def test_the_preference_beats_the_system(store, monkeypatch, posix_locale):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    store.set_language("fr")
    assert i18n.effective_language() == "fr"


def test_without_a_preference_the_system_decides(store, monkeypatch, posix_locale):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    i18n.invalidate()
    assert i18n.effective_language() == "fr"


def test_an_unknown_system_language_falls_back_to_english(store, monkeypatch, posix_locale):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    i18n.invalidate()
    assert i18n.effective_language() == i18n.DEFAULT_LANGUAGE == "en"


def test_the_resolution_is_memoised_and_invalidatable(store, monkeypatch):
    monkeypatch.setenv(i18n.ENV_VAR, "en")
    i18n.invalidate()
    assert i18n.effective_language() == "en"
    # Without invalidation, the environment change is not seen — that is the price of the
    # cache, and it is deliberate: otherwise every translated label would re-read
    # `session.json`.
    monkeypatch.setenv(i18n.ENV_VAR, "fr")
    assert i18n.effective_language() == "en"
    i18n.invalidate()
    assert i18n.effective_language() == "fr"


# --- translation without a catalogue ------------------------------------------------------

def test_without_a_catalogue_the_english_msgid_is_returned_as_is(store, monkeypatch):
    """The fallback that makes a third-party process usable without a translation."""
    monkeypatch.setenv(i18n.ENV_VAR, "fr")
    i18n.invalidate()
    unheard_of = "A message no catalogue will ever contain"
    assert i18n.translate(unheard_of) == unheard_of


def test_the_marker_does_not_translate():
    assert i18n.N_("Rotation angle") == "Rotation angle"


# --- persisted preference -----------------------------------------------------------------

def test_the_preference_survives_a_restart(tmp_path):
    path = tmp_path / "session.json"
    SessionStore(path).set_language("fr")
    assert SessionStore(path).language() == "fr"


def test_none_hands_control_back_to_the_system(store):
    store.set_language("fr")
    store.set_language(None)
    assert store.language() is None


def test_an_unknown_language_is_refused(store):
    with pytest.raises(ValueError, match="unknown language"):
        store.set_language("de")
    assert store.language() is None


def test_the_label_is_normalised_before_being_written(store):
    store.set_language("fr-FR")
    assert store.language() == "fr"


def test_the_session_state_carries_the_choice_and_the_served_language(store, monkeypatch):
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    state = store.state()
    assert state["language"] is None  # "automatic"
    assert state["effective_language"] in i18n.LANGUAGES
    store.set_language("fr")
    assert store.state() == {**state, "language": "fr", "effective_language": "fr"}


def test_setting_the_preference_invalidates_the_memoisation(store, monkeypatch, posix_locale):
    """The defect that would have the server translate in the old language until restart."""
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n.invalidate()
    assert i18n.effective_language() == "en"
    store.set_language("fr")
    assert i18n.effective_language() == "fr"


# --- console parity -----------------------------------------------------------------------

def test_app_exposes_the_language_and_echoes_its_change(tmp_path, monkeypatch):
    app = Application()
    app._session = SessionStore(tmp_path / "session.json")
    i18n.set_preference_source(app._session.language)
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    echoes: list[str] = []
    app.on_echo = echoes.append

    app.set_language("fr")

    assert echoes == ["app.set_language('fr')"]
    assert app.language == "fr"
    assert app.language_override == "fr"

    app.set_language(None)
    assert app.language_override is None
    assert echoes[-1] == "app.set_language(None)"


# --- compiled catalogue -------------------------------------------------------------------

def test_the_french_catalogue_is_compiled_and_served(store, monkeypatch):
    """The ``.mo`` is versioned: without it, the application would speak English **silently**.

    That is the failure mode you only notice after a release, ``gettext`` being loaded with
    ``fallback=True``. The test takes a preprocessing message, because it crosses the whole
    chain: English msgid in the code, catalogue, effective language.
    """
    monkeypatch.setenv(i18n.ENV_VAR, "fr")
    i18n.invalidate()

    assert i18n.translate("no light: nothing to integrate") == "aucun light : rien à intégrer"
    assert i18n.translate("Deconvolution") == "Déconvolution"
    assert (i18n.translate("Master dark — {key}").format(key="g100")
            == "Master dark — g100")


def test_in_english_the_msgid_is_returned_as_is(store, monkeypatch):
    monkeypatch.setenv(i18n.ENV_VAR, "en")
    i18n.invalidate()

    assert i18n.translate("no light: nothing to integrate") == "no light: nothing to integrate"
