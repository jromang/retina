"""Test fixtures: synthetic image + temporary FITS, and an isolated config."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_config(tmp_path_factory):
    """Hijack ``RETINA_CONFIG_DIR`` **and** ``RETINA_CACHE_DIR``, for the whole session.

    Without this, the suite writes into the user's **real** configuration — library,
    perspectives, and above all the persistent measurement cache. Two consequences, the
    second far worse than the first: we dirty the workstation, and one run would serve the
    next measurements it believes it computed. A measurement test would then pass without
    measuring anything, and a regression would stay invisible.

    The cache follows the same rule, and for one more reason: it hosts the downloaded **AI
    models** (``cache_dir()/models/``), which weigh tens of megabytes. A test that triggers
    one would drop it into the workstation's ``~/.cache``, and find it again on the next
    pass — so it would no longer test the download.
    """
    root = tmp_path_factory.mktemp("config")
    cache = tmp_path_factory.mktemp("cache")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("RETINA_CONFIG_DIR", str(root))
        patch.setenv("RETINA_CACHE_DIR", str(cache))
        yield root


@pytest.fixture(autouse=True)
def neutral_preferences():
    """Return preferences to their defaults after each test.

    The configuration directory is isolated, but **shared by the whole session**: a
    preference set by one test would stay set for every following one. A test that depends
    on the GPU or on parallelism would then pass or fail depending on execution order — the
    kind of failure you can never reproduce on its own. It happened, hence this fixture.

    **Delegated** keys (language, reopening) are left alone: they live in ``session.json``
    and ``pinned_language`` already takes care of them.
    """
    yield
    from pathlib import Path

    from retina import preferences
    from retina.paths import config_path

    settings = preferences.current()
    settings._values = {}          # the in-memory cache would outlive the file
    Path(config_path("preferences.json")).unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def pinned_language(monkeypatch):
    """Pin the language to English, and forget the memoised resolution between two tests.

    Two reasons, and the second is the nastiest: without pinning, the suite would pass or
    fail depending on the workstation's ``LANG``, since server strings follow the system
    locale; and ``retina.i18n`` memoises its resolution (otherwise a ``process.list`` would
    re-read ``session.json`` once per label), so a test that sets a language preference
    would leave it to the next one.

    A test that wants French sets ``RETINA_LANGUAGE`` then calls ``i18n.invalidate()``.
    """
    from retina import i18n

    monkeypatch.setenv(i18n.ENV_VAR, "en")
    i18n.set_preference_source(None)
    yield
    # A source left in place would point at the `session.json` of an already deleted `tmp_path`.
    i18n.set_preference_source(None)


def synthetic_array(h: int = 64, w: int = 96, channels: int = 1) -> np.ndarray:
    """Gentle gradient + one bright point star, values in [0,1]."""
    ys = np.linspace(0.0, 0.3, h, dtype=np.float32)[:, None]
    xs = np.linspace(0.0, 0.2, w, dtype=np.float32)[None, :]
    base = ys + xs
    base[h // 2, w // 2] = 1.0  # point "star"
    data = np.repeat(base[:, :, None], channels, axis=2)
    return np.ascontiguousarray(np.clip(data, 0.0, 1.0), dtype=np.float32)


@pytest.fixture
def synthetic_image():
    from retina import Image

    return Image(synthetic_array())


@pytest.fixture
def fits_path(tmp_path):
    from retina import Image
    from retina.io.fits import save_fits

    p = tmp_path / "synthetic.fits"
    save_fits(str(p), Image(synthetic_array()))
    return str(p)
