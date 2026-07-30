"""Shared execution context — resolving images by identifier.

Lets PixelMath reference another view or window by its id. The domain stays decoupled from
the GUI and the application: the ``Application`` registers a *provider* here; in headless mode
one can register one too (or pass the images to PixelMath explicitly through ``set_images``).
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np

# provider: id -> Image | ndarray | None
_provider: Callable[[str], object] | None = None

# progress/cancellation monitor of the running process — THREAD-LOCAL: one worker
# = one thread = one monitor (no leakage between concurrent executions).
_tls = threading.local()


def set_monitor(monitor) -> None:
    """Install (or remove with ``None``) the current thread's :class:`ProgressMonitor`."""
    _tls.monitor = monitor


def get_monitor():
    return getattr(_tls, "monitor", None)


def set_image_provider(fn: Callable[[str], object] | None) -> None:
    global _provider
    _provider = fn


# The current application. Same intent as `_provider`: the domain stays decoupled from the
# shell, and it is the ``Application`` that registers itself here at construction time.
#
# The `Script` process needs it — it executes a file, which presupposes an `app` in its
# namespace — and `execute_on(view)` gives it only a view. Taking the module singleton would
# replay the script against the *wrong* application as soon as there is more than one, which
# is the case in every test.
_application: object | None = None


def set_application(app: object | None) -> None:
    global _application
    _application = app


def get_application() -> object | None:
    if _application is not None:
        return _application
    from ..app import app  # fallback: lazy import, otherwise a cycle at domain import time

    return app


def resolve_image_full(identifier: str) -> np.ndarray | None:
    """Return the complete ``(H, W, C)`` array of a named image, or None."""
    if _provider is None:
        return None
    img = _provider(identifier)
    if img is None:
        return None
    return img.data if hasattr(img, "data") else np.asarray(img)
