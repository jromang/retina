"""Application language — resolution and ``gettext`` catalogues.

A **domain** module: it depends only on the standard library, and certainly not on Babel,
which only steps in during development to extract and compile the catalogues
(``scripts/update_translations.py``). An ``import retina`` on a machine without Babel must
keep working, catalogue or no catalogue: ``gettext`` is loaded with ``fallback=True``, so a
language without a ``.mo`` returns the original message.

Three choices not to undo:

* **the msgid are in English.** That is the gettext convention, and it is what makes a
  third-party process usable without a catalogue: for want of a translation, the user reads
  English, never a technical key. The domain and the console therefore see English; the
  translation is applied **at the edge**, where a string leaves for the interface;
* **the resolution is ordered**: ``$RETINA_LANGUAGE`` (this is what the tests and CI pin) →
  the user's preference (``session.json``) → the system locale → English. The environment
  variable comes before the preference on purpose: it is the only lever available when the
  interface is not there to change the preference;
* **we never touch ``locale.setlocale``.** Calling it would set the locale of the whole
  process, hence number formatting — a decimal comma in a FITS written by a French user
  would be silent damage. The system locale is therefore read from the environment (POSIX)
  or through the Win32 API, with no side effect.
"""

from __future__ import annotations

import gettext as _gettext
import os
import sys
from collections.abc import Callable
from pathlib import Path

#: Name of the gettext domain, hence of the file: ``<locale>/LC_MESSAGES/retina.mo``.
DOMAIN = "retina"

#: Fallback language, and the language the msgid are written in.
DEFAULT_LANGUAGE = "en"

#: Languages for which we ship a complete catalogue.
LANGUAGES: tuple[str, ...] = ("en", "fr")

#: Environment variable with priority (tests, CI, headless launch).
ENV_VAR = "RETINA_LANGUAGE"

#: Root of the compiled catalogues, shipped in the package resources.
LOCALE_DIR = Path(__file__).resolve().parent / "resources" / "i18n"

#: Memoized resolution: ``(language, catalogue)``. Without it, translating the 354 parameter
#: labels of a ``process.list`` would re-read ``session.json`` 354 times.
_cache: tuple[str, _gettext.NullTranslations] | None = None


def normalize(tag: object) -> str | None:
    """Reduce a BCP-47 or POSIX tag to one of our languages (``fr-FR`` → ``fr``).

    Returns ``None`` for anything we cannot serve: better to fall through to the next source
    than to display a half-translated language.
    """
    if not isinstance(tag, str) or not tag:
        return None
    # "fr_FR.UTF-8@euro": the language is what precedes the first separator.
    base = tag.strip().replace("_", "-").split(".")[0].split("@")[0].split("-")[0].lower()
    return base if base in LANGUAGES else None


def system_language() -> str | None:
    """System language, with no side effect on the process locale."""
    if sys.platform == "win32":  # pragma: no cover — platform dependent
        return _windows_language()
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        # LANGUAGE is a list of preferences separated by ":" (GNU convention).
        for chunk in os.environ.get(name, "").split(":"):
            language = normalize(chunk)
            if language is not None:
                return language
    return None


def _windows_language() -> str | None:  # pragma: no cover — platform dependent
    try:
        import ctypes

        tampon = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(tampon, len(tampon)):
            return normalize(tampon.value)
    except Exception:
        return None
    return None


#: Source of the preference. ``Application.session`` registers **its** store here, so that
#: the resolved language always comes from the file the application really reads and writes —
#: without that, a hijacked store (tests, embedding) would write into one file while the
#: resolution read another, and the language would change with no visible effect.
_preference_source: Callable[[], str | None] | None = None


def set_preference_source(provider: Callable[[], str | None] | None) -> None:
    """Designate where the language preference comes from (see :attr:`_preference_source`)."""
    global _preference_source
    _preference_source = provider
    invalidate()


def _preference() -> str | None:
    """The user's explicit preference, if it is readable."""
    try:
        if _preference_source is not None:
            return normalize(_preference_source())
        from .session import SessionStore

        return normalize(SessionStore().language())
    except Exception:
        # An unreadable configuration must not prevent starting in English.
        return None


def effective_language() -> str:
    """The language actually served, after full resolution."""
    return _resolve()[0]


def _resolve() -> tuple[str, _gettext.NullTranslations]:
    global _cache
    if _cache is not None:
        return _cache
    language = (
        normalize(os.environ.get(ENV_VAR))
        or _preference()
        or system_language()
        or DEFAULT_LANGUAGE
    )
    catalog = _gettext.translation(
        DOMAIN, localedir=str(LOCALE_DIR), languages=[language], fallback=True
    )
    _cache = (language, catalog)
    return _cache


def invalidate() -> None:
    """Forget the memoized resolution.

    Called when the preference changes (:meth:`retina.session.SessionStore.set_language`)
    and by the tests, which move ``$RETINA_LANGUAGE`` from one case to the next.
    """
    global _cache
    _cache = None


def catalog(lang: str) -> _gettext.NullTranslations:
    """Catalogue of a **named** language, independently of the application's.

    The only caller is the documentation, which is served over HTTP and accepts a ``?lang=``:
    a page requested in English must be so **entirely**, title included, even if the
    application runs in French. ``gettext`` already memoizes its catalogues, so there is
    nothing to cache here.
    """
    return _gettext.translation(
        DOMAIN, localedir=str(LOCALE_DIR), languages=[lang], fallback=True
    )


def translate(message: str, lang: str | None = None) -> str:
    """Translate *message*, into the effective language or into *lang* when given."""
    if lang:
        return catalog(lang).gettext(message)
    return _resolve()[1].gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Singular/plural form — the plural is not binary everywhere (Russian has three)."""
    return _resolve()[1].ngettext(singular, plural, n)


def N_(message: str) -> str:
    """Mark a string for extraction **without** translating it right away.

    This is what parameter labels call for: they are written at class definition, once and
    for all, whereas the translation must follow the language of the moment. The domain
    therefore carries English, and ``server/handlers_process.py`` translates at serialization
    time.
    """
    return message


#: Shorthand for code that translates in use: ``from ..i18n import translate as _t``.
#:
#: **Not ``_``**, despite the gettext convention. The repository already uses ``_`` as a
#: throwaway variable (``for _ in range(n)``, ``a, _ = f()``) in a dozen modules, three of
#: them among those that translate. A loop would silently reassign the translation function,
#: and the next call would raise a ``TypeError`` dozens of lines away from the cause.
#: ``ruff`` reports the case (F402), but only when the two cross within the same scope: the
#: collision would stay latent elsewhere. Hence a name that cannot collide — and
#: ``babel.cfg`` declares ``_t`` as the extraction keyword, in place of ``_``.
_t = translate
