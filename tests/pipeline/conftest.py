"""Pipeline fixtures: a folder of synthetic raw frames, generated once per session.

The set is small (about twenty 64 KB files) but generating it is not free; since it is
read-only for the scan/grouping tests, ``session`` scope is enough. Tests that write
(runner, cache) get their own copy through ``tmp_path``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("astropy")


@pytest.fixture(scope="session")
def raws_mono(tmp_path_factory) -> str:
    from retina.pipeline.synthetic import make_dataset

    root = tmp_path_factory.mktemp("raws_mono")
    make_dataset(str(root), "mono")
    return str(root)


@pytest.fixture(scope="session")
def raws_framing(tmp_path_factory) -> str:
    """Smart telescope sweep: two mosaic panels, a single filter."""
    from retina.pipeline.synthetic import make_dataset

    root = tmp_path_factory.mktemp("raws_framing")
    make_dataset(str(root), "framing")
    return str(root)


@pytest.fixture(scope="session")
def raws_osc(tmp_path_factory) -> str:
    from retina.pipeline.synthetic import make_dataset

    root = tmp_path_factory.mktemp("raws_osc")
    make_dataset(str(root), "osc")
    return str(root)
