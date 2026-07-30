"""The ``fs.*`` family — the text-file transport of the script editor.

These tests check above all what *refuses*: a relative path, a file that is too large, a
missing parent directory. The family grants no new privilege (the console already gives the
whole disk away), but it must fail cleanly rather than with an internal error.
"""

from __future__ import annotations

import pytest
from retina.server.handlers_fs import MAX_TEXT_BYTES
from retina.server.rpc import DOMAIN_ERROR
from rpcsession import RpcFailure


async def test_write_then_read_round_trip(session, tmp_path):
    target = tmp_path / "recipe.py"
    written = await session.call("fs.write_text", path=str(target), text="app.open('x.fits')\n")
    assert written["path"] == str(target)

    read_back = await session.call("fs.read_text", path=str(target))
    assert read_back["text"] == "app.open('x.fits')\n"
    assert read_back["path"] == str(target)


async def test_listing_puts_directories_before_files(session, tmp_path):
    (tmp_path / "zzz_folder").mkdir()
    (tmp_path / "aaa.py").write_text("pass\n")
    (tmp_path / ".cache").mkdir()

    listing = await session.call("fs.list", path=str(tmp_path))
    names = [e["name"] for e in listing["entries"]]
    # Directories first despite the reverse alphabetical order; hidden entries are filtered.
    assert names == ["zzz_folder", "aaa.py"]
    assert listing["parent"] == str(tmp_path.parent)
    assert next(e for e in listing["entries"] if e["name"] == "aaa.py")["is_dir"] is False


async def test_listing_shows_hidden_entries_on_demand(session, tmp_path):
    (tmp_path / ".config").mkdir()
    listing = await session.call("fs.list", path=str(tmp_path), hidden=True)
    assert [e["name"] for e in listing["entries"]] == [".config"]


async def test_listing_without_a_path_returns_the_home_directory(session):
    from pathlib import Path

    listing = await session.call("fs.list")
    assert listing["path"] == str(Path.home())
    assert await session.call("fs.home") == str(Path.home())


async def test_a_relative_path_is_refused(session):
    # A relative path would be resolved against the server's current directory, which makes
    # no sense at all for the client — least of all in remote mode.
    with pytest.raises(RpcFailure) as error:
        await session.call("fs.read_text", path="recipe.py")
    assert error.value.code == DOMAIN_ERROR
    assert "absolute" in str(error.value)


async def test_a_file_that_is_too_large_is_refused(session, tmp_path):
    large = tmp_path / "large.txt"
    large.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    with pytest.raises(RpcFailure) as error:
        await session.call("fs.read_text", path=str(large))
    assert error.value.code == DOMAIN_ERROR
    assert "too large" in str(error.value)


async def test_writing_does_not_create_the_directory_tree(session, tmp_path):
    missing = tmp_path / "nowhere" / "recipe.py"
    with pytest.raises(RpcFailure) as error:
        await session.call("fs.write_text", path=str(missing), text="pass\n")
    assert error.value.code == DOMAIN_ERROR
    assert not missing.parent.exists()


async def test_file_not_found(session, tmp_path):
    with pytest.raises(RpcFailure) as error:
        await session.call("fs.read_text", path=str(tmp_path / "absent.py"))
    assert error.value.code == DOMAIN_ERROR


async def test_reading_tolerates_an_invalid_byte(session, tmp_path):
    # `errors="replace"`: a badly encoded file opens read-only rather than returning an RPC
    # error the editor would not know how to explain.
    target = tmp_path / "latin.py"
    target.write_bytes(b"# caf\xe9\n")
    read_back = await session.call("fs.read_text", path=str(target))
    assert read_back["text"].startswith("# caf")


async def test_the_methods_are_advertised(session):
    methods = await session.call("rpc.methods")
    assert {"fs.home", "fs.list", "fs.read_text", "fs.write_text", "fs.stat"} <= set(methods)


async def test_writing_does_not_trigger_a_snapshot(session, tmp_path):
    """Writing a script changes nothing in the domain: no `state.changed` to broadcast."""
    session.clear()
    await session.call("fs.write_text", path=str(tmp_path / "a.py"), text="pass\n")
    await session.drain()
    assert session.of("state.changed") == []


# --- file fingerprint (modification outside the application) -----------------
#
# The doctrine is stated at the top of handlers_fs.py: no filesystem watcher, but a
# `(size, mtime_ns)` fingerprint that the client reads before writing and on returning to the
# tab. What follows holds the contract that detection depends on.


async def test_reading_and_writing_return_the_fingerprint(session, tmp_path):
    target = tmp_path / "recipe.py"
    written = await session.call("fs.write_text", path=str(target), text="a = 1\n")
    assert written["size"] == target.stat().st_size
    assert written["mtime_ns"] == target.stat().st_mtime_ns

    read_back = await session.call("fs.read_text", path=str(target))
    # The same fingerprint on both sides: without that, the client would believe itself
    # divergent from the very first check following its own save.
    assert (read_back["size"], read_back["mtime_ns"]) == (written["size"], written["mtime_ns"])


async def test_stat_does_not_read_the_content(session, tmp_path):
    target = tmp_path / "large.py"
    target.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    # A file that `read_text` refuses stays queryable: checking that it has not moved must
    # not cost its size on the WebSocket.
    digest = await session.call("fs.stat", path=str(target))
    assert digest["exists"] is True
    assert "text" not in digest
    assert digest["size"] == MAX_TEXT_BYTES + 1


async def test_stat_of_a_missing_file_is_an_answer_not_an_error(session, tmp_path):
    # The question asked is "what is there on the disk?": "nothing" answers it.
    digest = await session.call("fs.stat", path=str(tmp_path / "never.py"))
    assert digest == {"path": str(tmp_path / "never.py"),
                         "exists": False, "size": 0, "mtime_ns": 0}


async def test_stat_of_a_directory_does_not_pretend_to_be_a_file(session, tmp_path):
    folder = tmp_path / "sub"
    folder.mkdir()
    assert (await session.call("fs.stat", path=str(folder)))["exists"] is False


async def test_stat_requires_an_absolute_path(session):
    with pytest.raises(RpcFailure) as error:
        await session.call("fs.stat", path="recipe.py")
    assert error.value.code == DOMAIN_ERROR


async def test_the_fingerprint_changes_on_an_external_rewrite(session, tmp_path):
    """The real case: the file is rewritten by a third party, at identical size."""
    import os

    target = tmp_path / "outside.py"
    before = await session.call("fs.write_text", path=str(target), text="a = 1\n")
    target.write_text("a = 2\n", encoding="utf-8")
    # mtime granularity can be coarse on some filesystems: we force a distinct date rather
    # than making the test depend on a clock.
    os.utime(target, ns=(before["mtime_ns"] + 2_000_000_000, before["mtime_ns"] + 2_000_000_000))

    after = await session.call("fs.stat", path=str(target))
    assert after["size"] == before["size"]  # same size, so the date is what decides
    assert after["mtime_ns"] != before["mtime_ns"]
