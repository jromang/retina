"""``app.keywords`` — reading a window's FITS header.

The data had always been there (``ImageWindow.keywords``, filled at open time) but was only
reachable from the console: the frontend's header panel had nothing to call. Parity demands
it, so the API comes first and the handler second — never the other way round.
"""

from __future__ import annotations

import pytest

pytest.importorskip("astropy")


@pytest.fixture
def file(tmp_path):
    """A FITS file carrying a complete observation identity."""
    import numpy as np
    from retina.io.fits import save_fits
    from retina.model.image import Image

    path = str(tmp_path / "light.fits")
    save_fits(path, Image(np.zeros((8, 8, 1), dtype=np.float32)),
              {"EXPTIME": 300.0, "FILTER": "Ha", "GAIN": 100, "INSTRUME": "ASI2600MC"})
    return path


# --- domain (console) ----------------------------------------------------------------

def test_the_keywords_are_readable_from_the_console(file):
    from retina.app import Application

    app = Application()
    app.open(file)

    keywords = app.keywords()
    assert keywords["EXPTIME"] == 300.0
    assert keywords["FILTER"] == "Ha"


def test_the_structural_keys_are_left_out(file):
    """``NAXIS``/``BITPIX`` describe the file, not the observation: they would drown out the
    handful of lines one opens a header to read."""
    from retina.app import Application

    app = Application()
    app.open(file)

    assert not {"NAXIS", "NAXIS1", "BITPIX", "SIMPLE"} & set(app.keywords())


def test_the_call_raises_with_no_window_open(file):
    from retina.app import Application

    with pytest.raises(RuntimeError, match="No active window"):
        Application().keywords()


# --- over the wire -------------------------------------------------------------------

async def test_the_handler_returns_the_same_keywords(session, client, file):
    window = await session.call("app.open", path=file)

    keywords = await session.call("app.keywords", window=window)

    assert keywords["FILTER"] == "Ha"
    assert keywords == client.retina.app.keywords(
        next(w for w in client.retina.app.windows if w.id == window))


async def test_a_window_without_a_header_returns_an_empty_dict(session):
    """The test image has never seen a file: no error, just an empty header."""
    assert await session.call("app.keywords", window="Test01") == {}


async def test_an_unknown_window_returns_a_domain_error(session):
    from rpcsession import RpcFailure

    with pytest.raises(RpcFailure) as exc:
        await session.call("app.keywords", window="NoSuch01")

    assert exc.value.code == -32000


async def test_reading_does_not_rebroadcast_a_snapshot(session):
    """A pure read must not cause the whole application state to be retransmitted."""
    session.clear()
    await session.call("app.keywords", window="Test01")
    await session.drain()

    assert not session.of("state.changed")
