"""Application entry point: ``python -m retina``.

Exists for packaging. Briefcase launches the application through ``python -m <module_name>``
and that is not configurable — ``AppConfig.main_module()`` returns the module name hard-coded.
Without this file, the installed executable would start on a ``No module named
retina.__main__``.

It launches the **web** shell (`retina.web`) — the project's only shell.

**This file is never imported by ``import retina``** — Python only loads ``__main__.py`` when
the package is executed explicitly. The headless pillar is therefore intact: the domain still
does not pull in aiohttp (`tests/server/test_headless_parity.py`).
"""

from __future__ import annotations

import sys

from .web import main

if __name__ == "__main__":
    sys.exit(main())
