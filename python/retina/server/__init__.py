"""Retina web shell — local server exposing the scriptable API to a TypeScript frontend.

This package is **optional**: it is never imported by the core, and ``import retina`` must pull
in neither aiohttp nor anything from here. The rule is checked by
``tests/server/test_headless_parity.py``, following the test that already forbids aiohttp in the
domain.

The server is only a **client** of the ``app`` API, on the same footing as the console. It
implements no business logic: every RPC call delegates to ``retina.app.*``, which produces its
Python echo. This is the "console/GUI parity" pillar of ARCHITECTURE.md, transposed to the web.

Deliberately free of any import: merely naming ``retina.server`` in a test's ``sys.modules``
must not cost the loading of aiohttp.
"""

from __future__ import annotations

__all__ = ["ServerApp", "create_app"]


def __getattr__(name: str):
    """Lazy import — ``from retina.server import ServerApp`` works without penalizing
    those who import the package for simple introspection."""
    if name in __all__:
        from .core import ServerApp, create_app

        return {"ServerApp": ServerApp, "create_app": create_app}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
