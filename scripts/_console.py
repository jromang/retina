"""Make a development script's own output safe on a Windows console.

The Windows console speaks cp1252, and Python raises ``UnicodeEncodeError`` rather than
substituting when a ``print`` carries a character it cannot encode. Since these scripts use
arrows, checkmarks and warning signs in their progress messages, that turns a cosmetic detail
into a failure — and a particularly annoying one, because it fires *after* the work is done:
``fetch_astap.py`` downloaded 105 MB, then exited non-zero on the arrow in its closing line.

Nothing on Linux or macOS, and nothing in a UTF-8 console, can reveal this. CI did.

``build_dist.py`` and ``retina.web`` each carried their own copy of the fix; six other scripts
carried none. One helper, called first thing in ``main()``.
"""

from __future__ import annotations

import sys


def configure() -> None:
    """Reconfigure stdout and stderr to UTF-8, replacing what cannot be encoded."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
