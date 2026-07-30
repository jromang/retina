"""``ChatService`` — the built-in assistant, powered by the user's Claude Code.

# Why the CLI, and not an API key

The assistant runs on the user's Claude subscription (Pro/Max): we launch the ``claude`` CLI
they installed and connected themselves, exactly as the IDE integrations do. The Claude Agent
SDK is set aside — it requires an API key, and Anthropic does not permit offering claude.ai
sign-in inside a third-party product. Consequence: no API-key fallback here, and no
``ANTHROPIC_*`` variable is injected into the process environment.

# One process per turn

``claude -p`` is "one shot": one conversation turn per process, with continuity coming from
``--resume <session_id>`` (empirically validated: the identifier stays stable and the context
survives from one process to the next). That choice makes interruption trivial and portable —
``terminate()`` — where a persistent process would call for an undocumented control protocol
on stdin. The cost (~1 s of startup per turn) is the price of an engine we do not maintain.
The alternative stays isolated behind ``_run_turn`` should it ever change.

# What the process is allowed to do

``--tools ""`` removes **every** built-in tool (Bash, Edit, Write…); only Retina's MCP tools
remain, auto-approved by ``--allowedTools "mcp__retina__*"`` — so no permission prompt can
block a process without a terminal. ``--strict-mcp-config`` ignores the MCP servers
configured elsewhere on the machine, and ``--setting-sources ""`` their CLAUDE.md files,
hooks and plugins: the assistant's session must depend on Retina alone. The token passed is
the **persistent** MCP token, bounded to ``/mcp``.

# The stream

The CLI emits ``stream-json``: one JSON line per event (init, text deltas, tool calls,
result). ``_parse_line`` — the only place that knows this non-contractual format — translates
it into ``chat.event`` events broadcast to the panel; any unknown type is ignored and logged,
never fatal.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .core import ServerApp

log = logging.getLogger("retina.server.chat")

#: The transcript kept in memory (and replayed to a client that connects).
MAX_BLOCKS = 400
#: Blocks rewritten into ``chat-session.json`` at the end of a turn.
PERSISTED_BLOCKS = 200
#: A longer tool argument is truncated in the event (the full JSON stays readable in the
#: tool's result on the MCP side, no need to duplicate it here).
MAX_ARG_CHARS = 80
MAX_SUMMARY_CHARS = 120

SESSION_FILE = "chat-session.json"
PROMPT_RESOURCE = Path(__file__).resolve().parent.parent / "resources" / "chat" / "system_prompt.md"

#: Limit of the stdout read buffer. Asyncio's default (64 KiB) is exceeded by a single line:
#: the CLI re-emits the content of a tool result on its stream, and a ``render_view`` sends a
#: base64 PNG through it. We raise it to 32 MiB — far beyond a thumbnail, well below what
#: would threaten memory.
STDOUT_LIMIT = 32 * 1024 * 1024

#: Minimum CLI version whose stream has been verified. Below it, we refuse rather than leave
#: the user facing turns that fail for no readable reason.
CLI_MIN_VERSION = (2, 1, 0)
#: Last **minor** against which the contract was replayed (see
#: ``tests/server/test_chat_contract.py``). Above it, we do not forbid — we warn: the format
#: is stable in practice, and blocking on a more recent version would cost the user more than
#: the risk it would cover.
CLI_TESTED_MAX = (2, 1)


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """``"2.1.215 (Claude Code)"`` → ``(2, 1, 215)``. ``None`` if unreadable."""
    if not text:
        return None
    head = text.strip().split()[0]
    parts = head.split(".")
    try:
        return tuple(int(p) for p in parts[:3])
    except ValueError:
        return None


@dataclass
class ChatBlock:
    """One transcript element — the shape the panel displays."""

    kind: Literal["user", "text", "tool_call", "tool_result", "turn_done", "error"]
    text: str = ""
    tool: str | None = None
    args: dict | None = None
    ok: bool | None = None
    turn: int = 0

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")} | {
            "kind": self.kind, "turn": self.turn
        }


@dataclass
class ChatStatus:
    installed: bool = False
    version: str | None = None
    #: ``None`` = not probed yet; the probe (``claude auth status``) is free.
    authenticated: bool | None = None
    subscription: str | None = None
    busy: bool = False
    mcp_available: bool = False
    session: str | None = None
    #: Version at least equal to :data:`CLI_MIN_VERSION` (true if unreadable: a doubt about
    #: the number must not turn into a refusal).
    version_supported: bool = True
    #: Version more recent than the last one tested — informative, not blocking.
    version_untested: bool = False

    def to_dict(self) -> dict:
        ready = bool(
            self.installed and self.authenticated and self.mcp_available and self.version_supported
        )
        return {**asdict(self), "ready": ready, "min_version": _format_version(CLI_MIN_VERSION)}


def _format_version(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


class ChatService:
    """One conversation, one service — attached to the :class:`ServerApp`."""

    def __init__(
        self,
        server: ServerApp,
        *,
        binary: Sequence[str] | None = None,
        config_dir: Path | None = None,
        model: str | None = None,
    ) -> None:
        self._server = server
        self._binary_override = list(binary) if binary is not None else None
        self._config_dir = config_dir
        #: ``None`` = the CLI's default model, that is to say the user's choice. Force it
        #: only for a specific reason (the contract test takes a small model so as not to
        #: cost much).
        self._model = model
        self._status = ChatStatus()
        self._probed = False
        self._session_id: str | None = None
        self._blocks: list[ChatBlock] = []
        self._turn = 0
        self._turn_task: asyncio.Task | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._restore()

    # ----------------------------------------------------------------- state --
    @property
    def busy(self) -> bool:
        return self._turn_task is not None and not self._turn_task.done()

    async def status(self, refresh: bool = False) -> dict:
        """Installed? connected? ready? — what the panel displays before conversing."""
        if refresh or not self._probed:
            await self._probe()
        self._status.busy = self.busy
        self._status.mcp_available = self._server.mcp is not None
        self._status.session = self._session_id
        return self._status.to_dict()

    def transcript(self) -> list[dict]:
        """The current transcript — rehydration of a client that arrives mid-course."""
        return [b.to_dict() for b in self._blocks]

    # ----------------------------------------------------------------- turns --
    def send(self, text: str) -> dict:
        """Start a turn. Answers immediately; the stream arrives through ``chat.event``."""
        from .rpc import DOMAIN_ERROR, RpcError

        if self.busy:
            raise RpcError(DOMAIN_ERROR, "a turn is already in progress")
        if self._server.mcp is None:
            raise RpcError(DOMAIN_ERROR, "the MCP server is not mounted")
        if not text.strip():
            raise RpcError(DOMAIN_ERROR, "empty message")

        self._turn += 1
        self._append(ChatBlock(kind="user", text=text, turn=self._turn))
        self._notify({"type": "turn_started", "turn": self._turn})
        self._turn_task = asyncio.get_running_loop().create_task(self._run_turn(text))
        return {"turn": self._turn}

    async def interrupt(self) -> bool:
        """Kill the current turn's process. The session context itself survives.

        A small race, knowingly accepted: between ``send`` and the birth of the subprocess
        there is nothing to kill — we wait briefly for it to exist rather than cancel the
        task, whose cancellation semantics would run through the whole ``finally`` block.
        """
        if not self.busy:
            return False
        for _ in range(40):  # up to ~2 s: the spawn is much faster
            if self._process is not None or not self.busy:
                break
            await asyncio.sleep(0.05)
        process = self._process
        if process is None or process.returncode is not None:
            return False
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except TimeoutError:
            process.kill()
        return True

    def new_conversation(self) -> None:
        """Forget the session: the next turn starts from scratch."""
        from .rpc import DOMAIN_ERROR, RpcError

        if self.busy:
            raise RpcError(DOMAIN_ERROR, "a turn is in progress — interrupt it first")
        self._session_id = None
        self._blocks = []
        self._turn = 0
        self._persist()
        self._notify({"type": "cleared"})

    async def shutdown(self) -> None:
        """Server shutdown: the turn in flight is cleanly abandoned."""
        if self._turn_task is not None and not self._turn_task.done():
            self._turn_task.cancel()
        await self.interrupt()

    # ---------------------------------------------------------------- engine --
    async def _run_turn(self, prompt: str) -> None:
        turn = self._turn
        outcome_status = "error"
        error: str | None = None
        #: Machine code of the failure reason, when one exists that the client can name.
        #: The server sends the code, the client composes the sentence — as everywhere else.
        reason: str | None = None
        try:
            command = self._command()
            self._process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._effective_config_dir()),
                limit=STDOUT_LIMIT,
            )
            assert self._process.stdin is not None and self._process.stdout is not None
            self._process.stdin.write(prompt.encode("utf-8"))
            await self._process.stdin.drain()
            self._process.stdin.close()

            turn_session: str | None = None
            result_seen = False
            #: Lines received, and lines we managed to get something out of. The gap between
            #: the two is what distinguishes "the CLI said nothing" from "the CLI speaks a
            #: language this parser no longer understands".
            lines_seen = 0
            understood = 0
            while True:
                raw = await self._process.stdout.readline()
                if not raw:
                    break
                lines_seen += 1
                event = self._parse_line(raw, turn)
                if event is None:
                    continue
                understood += 1
                if event.get("_session_id"):
                    turn_session = event.pop("_session_id")
                if event.get("type") == "turn_result":
                    result_seen = True
                    outcome_status = "ok" if not event.get("is_error") else "error"
                    error = event.get("error")
                    if event.get("auth_failed"):
                        outcome_status = "auth_error"
                    continue
                self._notify(event)

            returncode = await self._process.wait()
            if not result_seen:
                # Stream cut off with no final message: three causes to tell apart, because
                # they call for three different user actions.
                if returncode != 0:
                    outcome_status = "interrupted"  # `terminate()`, or a dead CLI
                elif lines_seen and understood == 0:
                    # The CLI spoke, abundantly perhaps, and nothing came out of it: that is
                    # the signature of a format that changed under our feet. Say so
                    # explicitly rather than return an empty error — the user cannot guess
                    # that they need to update Retina.
                    reason = "unparsed_stream"
                    log.warning(
                        "unrecognized Claude Code stream (%d lines, version %s)",
                        lines_seen, self._status.version,
                    )
                elif lines_seen == 0:
                    reason = "no_output"
            # The id is kept only for a turn carried to completion: resuming a session whose
            # last turn was killed mid-course would replay an uncertain state.
            if result_seen and turn_session:
                self._session_id = turn_session
        except FileNotFoundError:
            outcome_status = "error"
            reason = "not_installed"
            self._probed = False  # the next `status()` will re-probe
        except asyncio.CancelledError:
            outcome_status = "interrupted"
            raise
        except Exception as exc:  # pragma: no cover — safety net
            log.exception("chat turn failed")
            outcome_status = "error"
            error = f"{type(exc).__name__}: {exc}"
        finally:
            self._process = None
            if outcome_status == "auth_error":
                self._status.authenticated = False
                self._notify({"type": "status", **self._status.to_dict()})
            self._append(ChatBlock(kind="turn_done", text=outcome_status, turn=turn))
            self._persist()
            self._notify(
                {"type": "turn_done", "turn": turn, "status": outcome_status,
                 **({"error": error} if error else {}),
                 **({"reason": reason} if reason else {})}
            )

    def _command(self) -> list[str]:
        from .security import mcp_token

        binary = self._binary_override or self._find_claude()
        mcp_config = json.dumps(
            {
                "mcpServers": {
                    "retina": {
                        "type": "http",
                        "url": f"http://127.0.0.1:{self._server.port}/mcp",
                        "headers": {"X-Retina-Token": mcp_token()},
                    }
                }
            }
        )
        command = [
            *binary,
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            # The assistant's session depends on Retina alone: neither the user's CLAUDE.md
            # files and hooks, nor the MCP servers configured elsewhere on the machine.
            "--setting-sources", "",
            "--strict-mcp-config",
            "--mcp-config", mcp_config,
            # No built-in tools; ours, auto-approved — no permission prompt can block a
            # process without a terminal.
            "--tools", "",
            "--allowedTools", "mcp__retina__*",
            "--append-system-prompt", self._system_prompt(),
        ]
        if self._model:
            command += ["--model", self._model]
        if self._session_id:
            command += ["--resume", self._session_id]
        return command

    def _find_claude(self) -> list[str]:
        """The repository's discovery pattern: explicit env, then PATH."""
        import os

        explicit = os.environ.get("RETINA_CLAUDE_BIN")
        if explicit:
            return [explicit]
        found = shutil.which("claude")
        if found is None:
            raise FileNotFoundError("claude")
        return [found]

    def _system_prompt(self) -> str:
        from ..process.registry import user_process_dir

        # The directory is created here: we announce it to the assistant in the prompt, so it
        # must exist for its `open_script(path=…/x.py)` to succeed on the first try
        # (otherwise `fs.write_text` refuses a nonexistent parent, and the assistant loses a
        # turn creating it).
        directory = user_process_dir()
        with contextlib.suppress(OSError):  # rights, full disk: the assistant will create it
            directory.mkdir(parents=True, exist_ok=True)
        template = PROMPT_RESOURCE.read_text(encoding="utf-8")
        return template.format(
            language=self._server.app.language or "English",
            user_process_dir=str(directory),
        )

    # -------------------------------------------------------------- parser --
    def _parse_line(self, raw: bytes, turn: int) -> dict | None:
        """Translate one stream-json line from the CLI into a ``chat.event`` event.

        The only place that knows this format. Types observed (CLI 2.1.215):
        ``system/init`` (carries ``session_id``), ``system/*`` (ignored),
        ``rate_limit_event`` (ignored), ``stream_event`` (the API's SSE — we keep only the
        ``text_delta``), ``assistant`` (full message: ``tool_use`` blocks, and
        ``error: authentication_failed`` when the CLI is not connected), ``user`` (tool
        results) and ``result`` (end of turn). Everything else is ignored.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("unreadable stream-json line: %r", raw[:200])
            return None
        if not isinstance(data, dict):
            return None
        kind = data.get("type")

        if kind == "system" and data.get("subtype") == "init":
            return {"type": "noop", "_session_id": data.get("session_id")}

        if kind == "stream_event":
            delta = data.get("event", {}).get("delta", {})
            if delta.get("type") == "text_delta" and delta.get("text"):
                self._merge_text(delta["text"], turn)
                return {"type": "text_delta", "turn": turn, "text": delta["text"]}
            return None

        if kind == "assistant":
            if data.get("error") == "authentication_failed":
                return None  # the `result` message of the same turn will carry the failure
            for block in data.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool = str(block.get("name", "")).removeprefix("mcp__retina__")
                    args = _trim_args(block.get("input") or {})
                    self._append(ChatBlock(kind="tool_call", tool=tool, args=args, turn=turn))
                    return {"type": "tool_call", "turn": turn,
                            "id": block.get("id"), "tool": tool, "args": args}
            return None

        if kind == "user":
            for block in data.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    ok = not bool(block.get("is_error"))
                    summary = _summarize(block.get("content"))
                    self._append(ChatBlock(kind="tool_result", text=summary, ok=ok, turn=turn))
                    return {"type": "tool_result", "turn": turn,
                            "id": block.get("tool_use_id"), "ok": ok, "summary": summary}
            return None

        if kind == "result":
            auth_failed = bool(data.get("is_error")) and "Not logged in" in str(
                data.get("result", "")
            )
            return {
                "type": "turn_result",
                "is_error": bool(data.get("is_error")),
                "error": str(data.get("result"))[:400] if data.get("is_error") else None,
                "auth_failed": auth_failed,
                "_session_id": data.get("session_id"),
            }

        return None

    def _merge_text(self, text: str, turn: int) -> None:
        """The transcript stores the merged prose (the stream itself goes out as deltas)."""
        if self._blocks and self._blocks[-1].kind == "text" and self._blocks[-1].turn == turn:
            self._blocks[-1].text += text
        else:
            self._append(ChatBlock(kind="text", text=text, turn=turn))

    # -------------------------------------------------------------- probes --
    async def _probe(self) -> None:
        """``claude --version`` then ``claude auth status`` — free, with no network call."""
        self._probed = True
        try:
            binary = self._binary_override or self._find_claude()
        except FileNotFoundError:
            self._status = ChatStatus(installed=False)
            return

        version = await self._run_probe([*binary, "--version"])
        if version is None:
            self._status = ChatStatus(installed=False)
            return
        self._status.installed = True
        self._status.version = version.strip().split()[0] if version.strip() else None
        parsed = parse_version(version)
        # An unreadable version does not block: better to try and fail with a clear message
        # than to refuse over a number we could not read.
        self._status.version_supported = parsed is None or parsed >= CLI_MIN_VERSION
        self._status.version_untested = parsed is not None and parsed[:2] > CLI_TESTED_MAX

        auth = await self._run_probe([*binary, "auth", "status"])
        if auth is None:
            self._status.authenticated = None  # probe unavailable: we will know on turn 1
            return
        try:
            parsed = json.loads(auth)
            self._status.authenticated = bool(parsed.get("loggedIn"))
            self._status.subscription = parsed.get("subscriptionType")
        except (json.JSONDecodeError, AttributeError):
            self._status.authenticated = None

    async def _run_probe(self, command: list[str]) -> str | None:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10.0)
        except (OSError, TimeoutError):
            return None
        if process.returncode != 0:
            return None
        return stdout.decode("utf-8", errors="replace")

    # -------------------------------------------------------- persistence --
    def _session_path(self) -> Path:
        if self._config_dir is not None:
            return self._config_dir / SESSION_FILE
        from ..paths import config_dir

        return config_dir() / SESSION_FILE

    def _persist(self) -> None:
        """Written at the end of a turn: the CLI keeps the context, we keep the display."""
        path = self._session_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "session_id": self._session_id,
                        "turn": self._turn,
                        "blocks": [b.to_dict() for b in self._blocks[-PERSISTED_BLOCKS:]],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover — full disk, rights…
            log.warning("chat session not saved: %s", exc)

    def _restore(self) -> None:
        path = self._session_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._session_id = data.get("session_id")
            self._turn = int(data.get("turn", 0))
            self._blocks = [
                ChatBlock(
                    kind=b["kind"], text=b.get("text", ""), tool=b.get("tool"),
                    args=b.get("args"), ok=b.get("ok"), turn=int(b.get("turn", 0)),
                )
                for b in data.get("blocks", [])
            ]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            log.warning("unreadable chat session, restarted from scratch (%s)", path)

    # ---------------------------------------------------------------- misc --
    def _effective_config_dir(self) -> Path:
        if self._config_dir is not None:
            return self._config_dir
        from ..paths import config_dir

        path = config_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _append(self, block: ChatBlock) -> None:
        self._blocks.append(block)
        if len(self._blocks) > MAX_BLOCKS:
            del self._blocks[: len(self._blocks) - MAX_BLOCKS]

    def _notify(self, event: dict) -> None:
        if event.get("type") == "noop":
            return
        self._server.broadcast.notify("chat.event", event)


def _trim_args(args: dict) -> dict:
    """The arguments shown to the panel: short scalars, everything else summarized."""
    trimmed: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, (int, float, bool)) or value is None:
            trimmed[key] = value
        else:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            trimmed[key] = text if len(text) <= MAX_ARG_CHARS else text[:MAX_ARG_CHARS] + "…"
    return trimmed


def _summarize(content: Any) -> str:
    """Opening of a tool result, flattened — the panel does not need the whole JSON.

    Flattened and not "first line": indented JSON results would all start with ``{``, which
    summarizes nothing.
    """
    if isinstance(content, list):
        for entry in content:
            if isinstance(entry, dict) and entry.get("type") == "text":
                content = entry.get("text", "")
                break
        else:
            content = ""
    flat = " ".join(str(content or "").split())
    return flat if len(flat) <= MAX_SUMMARY_CHARS else flat[:MAX_SUMMARY_CHARS] + "…"
