"""Built-in assistant: engine lifecycle, event stream, states, persistence.

No test launches the real Claude Code: the fake CLI (``fake_claude.py``) replays
stream-json lines copied from real captures. What these tests hold: the parser turns that
stream into usable ``chat.event`` events, an interrupt kills the turn without losing the
conversation, and the panel can always tell where it stands.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from retina.app import Application
from retina.server.core import ServerApp

pytest.importorskip("aiohttp", reason="extra [web] missing")

from retina.server.chat import ChatService

FAKE = str(Path(__file__).with_name("fake_claude.py"))


@pytest.fixture
def chat_server(domain: Application, tmp_path, monkeypatch):
    """A server whose chat points at the fake CLI, with an isolated config directory."""
    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path))
    server = ServerApp(domain, port=0, mcp=True)
    server.chat = ChatService(server, binary=[sys.executable, FAKE], config_dir=tmp_path)
    server.chat_handlers._chat = server.chat
    events: list[dict] = []
    notifications: list[tuple[str, dict]] = []

    def record(method: str, params: dict) -> None:
        notifications.append((method, params))
        if method == "chat.event":
            events.append(params)

    server.broadcast.notify = record  # type: ignore[method-assign]
    server.events = events  # type: ignore[attr-defined]
    server.notifications = notifications  # type: ignore[attr-defined]
    return server


async def _finish(server: ServerApp, timeout: float = 15.0) -> None:
    task = server.chat._turn_task
    assert task is not None
    await asyncio.wait_for(asyncio.shield(task), timeout)


# --- status -------------------------------------------------------------------
async def test_status_detects_the_cli_and_the_authentication(chat_server):
    status = await chat_server.chat.status()
    assert status["installed"] is True
    assert status["version"] == "9.9.9"
    assert status["authenticated"] is True
    assert status["subscription"] == "max"
    assert status["mcp_available"] is True
    assert status["ready"] is True


async def test_status_without_a_cli_says_not_installed(chat_server, monkeypatch):
    chat_server.chat._binary_override = None
    monkeypatch.delenv("RETINA_CLAUDE_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    status = await chat_server.chat.status(refresh=True)
    assert status["installed"] is False
    assert status["ready"] is False


async def test_status_logged_out(chat_server, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_IN", "0")
    status = await chat_server.chat.status(refresh=True)
    assert status["installed"] is True
    assert status["authenticated"] is False
    assert status["ready"] is False


# --- a single turn ------------------------------------------------------------
async def test_a_nominal_turn_streams_and_completes(chat_server):
    reply = chat_server.chat.send("What do you see?")
    assert reply == {"turn": 1}
    await _finish(chat_server)

    events = chat_server.events
    kinds = [e["type"] for e in events]
    assert kinds[0] == "turn_started"
    assert "text_delta" in kinds and "tool_call" in kinds and "tool_result" in kinds
    assert kinds[-1] == "turn_done" and events[-1]["status"] == "ok"

    # The tool call is pruned for the panel's benefit: name without its prefix, arguments
    # bounded — the full JSON has no business inside a chat bubble.
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["tool"] == "get_state"
    assert len(call["args"]["long_argument"]) <= 81

    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ok"] is True and "windows" in result["summary"]


async def test_the_transcript_merges_the_prose(chat_server):
    chat_server.chat.send("hello")
    await _finish(chat_server)

    blocks = chat_server.chat.transcript()
    text = [b for b in blocks if b["kind"] == "text"]
    # Two deltas, "I am looking at " + "the session." = a single prose block.
    assert text[0]["text"] == "I am looking at the session."
    assert [b["kind"] for b in blocks][:2] == ["user", "text"]


async def test_the_second_turn_resumes_the_session(chat_server, tmp_path, monkeypatch):
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_FILE", str(argv_file))

    chat_server.chat.send("first")
    await _finish(chat_server)
    first_argv = json.loads(argv_file.read_text())
    assert "--resume" not in first_argv

    chat_server.chat.send("second")
    await _finish(chat_server)
    second_argv = json.loads(argv_file.read_text())
    index = second_argv.index("--resume")
    assert second_argv[index + 1] == "11111111-2222-3333-4444-555555555555"


async def test_the_command_line_is_bounded(chat_server, tmp_path, monkeypatch):
    """The security contract lives in the argv: no built-in tools, strict MCP."""
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_FILE", str(argv_file))
    chat_server.chat.send("check")
    await _finish(chat_server)

    argv = json.loads(argv_file.read_text())
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--allowedTools") + 1] == "mcp__retina__*"
    assert "--strict-mcp-config" in argv
    assert "--dangerously-skip-permissions" not in argv
    config = json.loads(argv[argv.index("--mcp-config") + 1])
    retina = config["mcpServers"]["retina"]
    assert retina["url"].endswith("/mcp")
    assert retina["headers"]["X-Retina-Token"]
    prompt = argv[argv.index("--append-system-prompt") + 1]
    assert "mcp__retina__" in prompt and "{language}" not in prompt


async def test_a_huge_line_does_not_break_the_stream(chat_server, monkeypatch):
    """A ``render_view`` tool result ships a base64 PNG on a single line: past asyncio's
    default buffer (64 KiB), which therefore has to be raised."""
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "bigline")
    chat_server.chat.send("show")
    await _finish(chat_server)

    assert chat_server.events[-1]["status"] == "ok"
    result = next(e for e in chat_server.events if e["type"] == "tool_result")
    assert result["ok"] is True


async def test_a_dirty_stream_does_not_kill_the_turn(chat_server, monkeypatch):
    """The format is not contractual: the unknown is ignored, it does not break anything."""
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "garbage")
    chat_server.chat.send("robustness")
    await _finish(chat_server)

    assert chat_server.events[-1]["status"] == "ok"
    assert any(e["type"] == "text_delta" for e in chat_server.events)


# --- interruption -------------------------------------------------------------
async def test_interrupt_kills_the_turn_and_reports_it(chat_server, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "slow")
    chat_server.chat.send("long")
    for _ in range(100):  # wait for the process to be born and to have spoken
        await asyncio.sleep(0.05)
        if any(e["type"] == "text_delta" for e in chat_server.events):
            break

    assert await chat_server.chat.interrupt() is True
    await _finish(chat_server)

    assert chat_server.events[-1]["type"] == "turn_done"
    assert chat_server.events[-1]["status"] == "interrupted"
    # A killed turn does not record a session: resuming from an uncertain state is worse
    # than starting again from the last complete turn.
    assert chat_server.chat._session_id is None


async def test_send_during_a_turn_is_refused(chat_server, monkeypatch):
    from retina.server.rpc import RpcError

    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "slow")
    chat_server.chat.send("first")
    with pytest.raises(RpcError):
        chat_server.chat.send("second")
    await chat_server.chat.interrupt()
    await _finish(chat_server)


# --- authentication lost mid-flight ------------------------------------------
async def test_a_turn_without_a_login_flips_the_status(chat_server, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "noauth")
    chat_server.chat.send("who am I")
    await _finish(chat_server)

    assert chat_server.events[-1]["status"] == "auth_error"
    statuses = [e for e in chat_server.events if e["type"] == "status"]
    assert statuses and statuses[-1]["authenticated"] is False


# --- persistence --------------------------------------------------------------
async def test_the_conversation_survives_a_restart(chat_server, tmp_path):
    chat_server.chat.send("remember this")
    await _finish(chat_server)

    revived = ChatService(chat_server, binary=[sys.executable, FAKE], config_dir=tmp_path)
    assert revived._session_id == "11111111-2222-3333-4444-555555555555"
    kinds = [b["kind"] for b in revived.transcript()]
    assert "user" in kinds and "turn_done" in kinds


async def test_new_conversation_wipes_everything(chat_server, tmp_path):
    chat_server.chat.send("one turn")
    await _finish(chat_server)
    chat_server.chat.new_conversation()

    assert chat_server.chat.transcript() == []
    assert chat_server.chat._session_id is None
    persisted = json.loads((tmp_path / "chat-session.json").read_text())
    assert persisted["session_id"] is None and persisted["blocks"] == []


async def test_an_unreadable_session_starts_from_scratch(chat_server, tmp_path):
    (tmp_path / "chat-session.json").write_text("{broken", encoding="utf-8")
    revived = ChatService(chat_server, binary=[sys.executable, FAKE], config_dir=tmp_path)
    assert revived.transcript() == []


# --- guard rails --------------------------------------------------------------
async def test_send_without_mcp_is_refused(domain, tmp_path, monkeypatch):
    from retina.server.rpc import RpcError

    monkeypatch.setenv("RETINA_CONFIG_DIR", str(tmp_path))
    server = ServerApp(domain, port=0)  # mcp=False
    server.chat = ChatService(server, binary=[sys.executable, FAKE], config_dir=tmp_path)
    with pytest.raises(RpcError):
        server.chat.send("hello")


async def test_shutdown_during_a_turn(chat_server, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "slow")
    chat_server.chat.send("long")
    await asyncio.sleep(0.3)
    await chat_server.chat.shutdown()
    assert not chat_server.chat.busy


# --- version bounds -----------------------------------------------------------
def test_parse_version_reads_the_cli_output():
    from retina.server.chat import parse_version

    assert parse_version("2.1.215 (Claude Code)") == (2, 1, 215)
    assert parse_version("9.9.9") == (9, 9, 9)
    assert parse_version("unexpected") is None
    assert parse_version(None) is None


async def test_a_too_old_version_blocks(chat_server, monkeypatch):
    """Below the verified minimum, a clear screen beats turns that quietly fail."""
    import retina.server.chat as chat_module

    monkeypatch.setattr(chat_module, "CLI_MIN_VERSION", (99, 0, 0))
    status = await chat_server.chat.status(refresh=True)

    assert status["installed"] is True
    assert status["version_supported"] is False
    assert status["ready"] is False
    assert status["min_version"] == "99.0.0"


async def test_a_newer_version_warns_without_blocking(chat_server, monkeypatch):
    """The format is stable in practice: refusing would cost more than the risk covered."""
    import retina.server.chat as chat_module

    monkeypatch.setattr(chat_module, "CLI_TESTED_MAX", (2, 1))  # the fake CLI says 9.9.9
    status = await chat_server.chat.status(refresh=True)

    assert status["version_untested"] is True
    assert status["version_supported"] is True
    assert status["ready"] is True


async def test_an_unreadable_version_does_not_block(chat_server, monkeypatch):
    """A doubt about the number must not turn into a refusal."""
    from retina.server.chat import ChatStatus

    async def probe_unreadable(_command):
        return "unknown version\n"

    chat_server.chat._status = ChatStatus()
    monkeypatch.setattr(chat_server.chat, "_run_probe", probe_unreadable)
    status = await chat_server.chat.status(refresh=True)

    assert status["version_supported"] is True


# --- failure reasons ----------------------------------------------------------
async def test_an_unintelligible_stream_is_named(chat_server, monkeypatch, tmp_path):
    """The case that matters: the CLI spoke, and the parser recognised none of it.

    That is the signature of a format that has changed. The user cannot guess it: the turn
    must say *why*, not return a bare error.
    """
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "alien")
    chat_server.chat.send("hello")
    await _finish(chat_server)

    last = chat_server.events[-1]
    assert last["status"] == "error"
    assert last["reason"] == "unparsed_stream"


async def test_a_mute_cli_is_told_apart(chat_server, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", "silent")
    chat_server.chat.send("hello")
    await _finish(chat_server)

    assert chat_server.events[-1]["reason"] == "no_output"


async def test_a_missing_cli_is_named(chat_server, monkeypatch):
    chat_server.chat._binary_override = ["/nowhere/claude"]
    chat_server.chat.send("hello")
    await _finish(chat_server)

    assert chat_server.events[-1]["reason"] == "not_installed"
