"""Config/cache locations — the three branches, and no caching at import time."""

from __future__ import annotations

from pathlib import Path

from retina import paths


def test_config_dir_follows_retina_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path))
    assert paths.config_dir() == tmp_path
    assert paths.config_path("library") == tmp_path / "library"


def test_config_dir_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("RETINA_CONFIG_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert paths.config_dir() == tmp_path / "retina"


def test_config_dir_defaults_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("RETINA_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.config_dir() == tmp_path / ".config" / "retina"


def test_cache_dir_is_distinct_from_config(monkeypatch, tmp_path):
    """The cache is not the config: wiping astrometric indexes must not take the
    recipe library with it."""
    monkeypatch.delenv("RETINA_CACHE_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path / "conf"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root = tmp_path / "cache" / "retina"
    assert paths.cache_dir() == root
    assert paths.cache_path("astrometry-indexes") == root / "astrometry-indexes"


def test_resolution_happens_on_every_call_not_at_import(monkeypatch, tmp_path):
    """A variable set after the import must be seen — otherwise the ``isolated_config``
    fixture would isolate nothing and the suite would write to the real config."""
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path / "a"))
    first = paths.config_dir()
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path / "b"))
    assert paths.config_dir() != first


def test_the_four_consumers_share_the_root(monkeypatch, tmp_path):
    """The library, the perspectives and the measurement cache are neighbours."""
    from retina.library import _default_root
    from retina.pipeline.measure_cache import _default_root as _measures_root
    from retina.server.layout_backend import _perspectives_root

    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path))
    assert Path(_default_root()) == tmp_path / "library"
    assert _perspectives_root() == tmp_path / "perspectives"
    assert _measures_root() == tmp_path / "measure-cache"
