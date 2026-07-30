"""Claude Code CLI contract — the only test that talks to the **real** binary.

# Why it exists

The CLI's ``stream-json`` format is not published: it is the interface Anthropic's Claude
Agent SDK uses to drive that same binary, so it is stable in practice, but nothing guarantees
it to us in writing. The rest of the suite runs against a fake CLI (``fake_claude.py``) that
replays captured lines: unbeatable for the logic, blind by construction to a change in the
real format. Without this test, a breakage would surface as a user bug report; with it, it
surfaces on the day we run it.

# Why it is outside ``pytest -q``

It starts real sessions: it requires a CLI that is installed **and logged in**, it burns
quota, and it takes a few seconds. So it must not run in the ordinary development loop. We
turn it on explicitly:

    RETINA_CLI_CONTRACT=1 pytest tests/server/test_chat_contract.py -v

Run it after a Claude Code update, or before a release. If it breaks, the procedure is in
``ARCHITECTURE.md``: recapture real lines and realign the fake CLI.

The model is forced to ``haiku``: this test checks a **format**, not intelligence.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest
from retina.app import Application
from retina.server.core import ServerApp

pytest.importorskip("aiohttp", reason="[web] extra missing")

from aiohttp.test_utils import TestClient, TestServer
from retina.server.chat import CLI_MIN_VERSION, ChatService, parse_version

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("RETINA_CLI_CONTRACT"),
        reason="contract test: set RETINA_CLI_CONTRACT=1 to enable it",
    ),
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude not found"),
]

TIMEOUT = 180.0


@pytest.fixture
async def live(domain: Application, tmp_path, monkeypatch):
    """A server that is **actually listening**: the CLI has to be able to reach ``/mcp``."""
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path))
    server = ServerApp(domain, port=0, mcp=True)
    server.attach()
    async with TestClient(TestServer(server.aio)) as client:
        # The real port replaces the 0: that is the one `--mcp-config` will carry.
        server.port = client.server.port
        server.chat = ChatService(server, config_dir=tmp_path, model="haiku")
        events: list[dict] = []
        original = server.broadcast.notify

        def record(method: str, params: dict) -> None:
            if method == "chat.event":
                events.append(params)
            original(method, params)

        server.broadcast.notify = record  # type: ignore[method-assign]
        server.events = events  # type: ignore[attr-defined]
        yield server
    await server.chat.shutdown()
    server.detach()


async def _run(server: ServerApp, text: str) -> list[dict]:
    server.chat.send(text)
    task = server.chat._turn_task
    assert task is not None
    await asyncio.wait_for(asyncio.shield(task), TIMEOUT)
    return list(server.events)


async def test_the_installed_cli_meets_the_minimum_version(live):
    status = await live.chat.status(refresh=True)
    assert status["installed"] is True
    parsed = parse_version(status["version"])
    assert parsed is not None, f"unreadable version: {status['version']!r}"
    assert parsed >= CLI_MIN_VERSION, "the local CLI is older than our minimum"
    if not status["authenticated"]:
        pytest.skip("claude installed but not logged in — `claude auth login`")


async def test_the_stream_yields_the_expected_events(live):
    """The three invariants the parser depends on, over a turn without tools."""
    status = await live.chat.status(refresh=True)
    if not status["authenticated"]:
        pytest.skip("claude not logged in")

    events = await _run(live, "Reply with exactly: OK")

    kinds = [e["type"] for e in events]
    assert kinds[0] == "turn_started"
    assert "text_delta" in kinds, "no text delta: the streaming shape has changed"
    assert kinds[-1] == "turn_done"
    assert events[-1]["status"] == "ok", events[-1]
    # A second turn only makes sense if the first one handed us a session identifier.
    assert live.chat._session_id, "no session_id captured: `--resume` would not work"


async def test_the_mcp_tools_are_reachable_and_read(live):
    """The full contract: `--mcp-config` with a header, the allowlist, and a tool result.

    This is the test worth the most: it covers both the stream format and the fact that the
    CLI accepts our inline MCP configuration — two undocumented things.
    """
    status = await live.chat.status(refresh=True)
    if not status["authenticated"]:
        pytest.skip("claude not logged in")

    events = await _run(
        live,
        "Call the get_state tool and reply with the number of open image windows. Nothing else.",
    )

    calls = [e for e in events if e["type"] == "tool_call"]
    assert calls, "no tool call: the MCP configuration did not get through"
    assert calls[0]["tool"] == "get_state", calls[0]
    results = [e for e in events if e["type"] == "tool_result"]
    assert results and results[0]["ok"] is True, results
    # The `domain` fixture opens a window: the tool must see *our* session.
    assert "Test01" in results[0]["summary"] or "windows" in results[0]["summary"]
    assert events[-1]["status"] == "ok"


async def test_the_session_resumes_from_one_turn_to_the_next(live):
    status = await live.chat.status(refresh=True)
    if not status["authenticated"]:
        pytest.skip("claude not logged in")

    await _run(live, "Remember the number 7. Reply with just: stored")
    first = live.chat._session_id
    live.events.clear()
    events = await _run(live, "What number did I ask you to remember? Reply with the digit only.")

    assert live.chat._session_id == first, "the session identifier changed along the way"
    text = "".join(e.get("text", "") for e in events if e["type"] == "text_delta")
    assert "7" in text, f"the context does not survive --resume: {text!r}"
