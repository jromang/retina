"""Locations of the user configuration and cache.

A single convention, applied everywhere: ``$RETINA_CONFIG_DIR`` when the variable is set
(that is what the tests hijack, see the ``isolated_config`` fixture), otherwise
``%APPDATA%/retina`` on Windows, otherwise ``$XDG_CONFIG_HOME|~/.config`` + ``/retina``.

This module exists because that logic was **copied four times** — library, perspectives,
measurement cache, console history — with small divergences (one returned a ``str``, another
created the directory on the way). Resolution happens on **every call** and never at import
time: an environment variable set after the module is loaded must be seen, otherwise a test
that isolates the configuration would isolate nothing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def config_dir() -> Path:
    """Root of the user configuration (the directory is **not** created)."""
    base = os.environ.get("RETINA_CONFIG_DIR")
    if base:
        return Path(base)
    if sys.platform == "win32":  # pragma: no cover — platform dependent
        return Path(os.environ.get("APPDATA", Path.home())) / "retina"
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "retina"


def config_path(*parts: str) -> Path:
    """``config_dir()`` followed by *parts*, without creating the directory."""
    return config_dir().joinpath(*parts)


def cache_dir() -> Path:
    """Root of the user cache (rebuildable data: astrometric indexes…).

    Follows ``$RETINA_CACHE_DIR`` then the XDG cache convention, distinct from the config:
    this is bulky data a user must be able to erase without losing their settings. On Windows,
    for want of a widespread separate equivalent, we fall back on the config.
    """
    base = os.environ.get("RETINA_CACHE_DIR")
    if base:
        return Path(base)
    if sys.platform == "win32":  # pragma: no cover — platform dependent
        return config_dir() / "cache"
    xdg = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    return Path(xdg) / "retina"


def cache_path(*parts: str) -> Path:
    """``cache_dir()`` followed by *parts*, without creating the directory."""
    return cache_dir().joinpath(*parts)
