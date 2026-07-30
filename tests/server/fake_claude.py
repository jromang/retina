"""Fake ``claude`` CLI — replays the stream-json lines captured from the real one (2.1.215).

Started by the tests through ``ChatService(binary=[sys.executable, __file__])``: no PATH, no
shebang, portable on Windows. Scenarios are selected by environment variables — the service
passes nothing else to its subprocess.

The lines emitted are **structural copies** of real captures: if the CLI format ever changes,
this is the file to realign on fresh captures, and the tests then tell us what the parser no
longer understands.
"""

from __future__ import annotations

import json
import os
import sys
import time

SESSION_ID = os.environ.get("FAKE_CLAUDE_SESSION_ID", "11111111-2222-3333-4444-555555555555")


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _init() -> None:
    _emit(
        {
            "type": "system", "subtype": "init", "cwd": os.getcwd(),
            "session_id": SESSION_ID,
            "tools": ["mcp__retina__get_state", "mcp__retina__apply_process"],
            "mcp_servers": [{"name": "retina", "status": "connected"}],
            "model": "claude-haiku-4-5-20251001", "permissionMode": "default",
            "apiKeySource": "none",
        }
    )


def _delta(text: str) -> None:
    _emit(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta", "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
            "session_id": SESSION_ID,
        }
    )


def _result(text: str, *, is_error: bool = False) -> None:
    _emit(
        {
            "type": "result", "subtype": "success" if not is_error else "error",
            "is_error": is_error, "num_turns": 1, "result": text,
            "session_id": SESSION_ID, "total_cost_usd": 0,
        }
    )


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        print("9.9.9 (Claude Code)")
        return 0
    if args[:2] == ["auth", "status"]:
        logged_in = os.environ.get("FAKE_CLAUDE_LOGGED_IN", "1") == "1"
        print(json.dumps({"loggedIn": logged_in, "authMethod": "claude.ai",
                          "subscriptionType": "max" if logged_in else None}))
        return 0

    dump = os.environ.get("FAKE_CLAUDE_ARGV_FILE")
    if dump:
        with open(dump, "w", encoding="utf-8") as handle:
            json.dump(args, handle)

    prompt = sys.stdin.read()
    scenario = os.environ.get("FAKE_CLAUDE_SCENARIO", "nominal")

    if scenario == "noauth":
        _init()
        _emit({"type": "assistant", "error": "authentication_failed",
               "message": {"content": [{"type": "text", "text": "Not logged in"}]},
               "session_id": SESSION_ID})
        _result("Not logged in · Please run /login", is_error=True)
        return 1

    if scenario == "slow":
        _init()
        _delta("Thinking…")
        time.sleep(60)  # the test interrupts long before that
        return 0

    if scenario == "bigline":
        # A single stdout line larger than the default buffer (64 KiB): what a `render_view`
        # tool result produces (base64 PNG). The service must read it all the same.
        _init()
        _emit(
            {
                "type": "user",
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "toolu_big",
                     "content": [{"type": "text", "text": "A" * 200_000}]},
                ]},
                "session_id": SESSION_ID,
            }
        )
        _delta("thumbnail rendered.")
        _result("done")
        return 0

    if scenario == "alien":
        # The CLI speaks, and not one word of it means anything to us: what a wholly
        # redesigned format would produce.
        for i in range(5):
            _emit({"type": f"tomorrows_format_{i}", "payload": {"n": i}})
        return 0

    if scenario == "silent":
        return 0

    if scenario == "garbage":
        _init()
        sys.stdout.write("not JSON at all\n")
        _emit({"type": "unknown_type_from_the_future", "session_id": SESSION_ID})
        _delta("Useful nonetheless.")
        _result("Useful nonetheless.")
        return 0

    # nominal: prose, a tool call, its result, a conclusion.
    _init()
    _emit({"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 12,
           "session_id": SESSION_ID})
    _emit({"type": "rate_limit_event", "rate_limit_info": {}, "session_id": SESSION_ID})
    _delta("I am looking at ")
    _delta("the session.")
    _emit(
        {
            "type": "assistant",
            "message": {"content": [
                {"type": "text", "text": "I am looking at the session."},
                {"type": "tool_use", "id": "toolu_01", "name": "mcp__retina__get_state",
                 "input": {"long_argument": "x" * 500}},
            ]},
            "session_id": SESSION_ID,
        }
    )
    _emit(
        {
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "toolu_01",
                 "content": [{"type": "text", "text": '{\n  "windows": []\n}'}]},
            ]},
            "session_id": SESSION_ID,
        }
    )
    _delta(f"You told me: {prompt.strip()[:40]}")
    _result("end of turn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
