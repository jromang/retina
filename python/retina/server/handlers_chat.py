"""``chat.*`` family — the assistant panel, protocol side.

No method is mutating: the domain mutations the assistant triggers go through its MCP tools,
which are already instrumented (jobs, echo, snapshot). Only the conversation and its state
travel through here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chat import ChatService

CHAT_METHODS: dict[str, bool] = {
    "chat.status": False,
    "chat.send": False,
    "chat.interrupt": False,
    "chat.new": False,
    "chat.transcript": False,
}


class ChatHandlers:
    def __init__(self, chat: ChatService) -> None:
        self._chat = chat

    async def status(self, refresh: bool = False) -> dict:
        """Installed, logged in, ready — what the panel displays before conversing."""
        return await self._chat.status(bool(refresh))

    def send(self, text: str) -> dict:
        """Starts a turn and returns immediately; the stream arrives via ``chat.event``."""
        return self._chat.send(text)

    async def interrupt(self) -> bool:
        """Interrupts the current turn (the conversation context survives)."""
        return await self._chat.interrupt()

    def new(self) -> None:
        """New conversation: transcript and session start over from scratch."""
        self._chat.new_conversation()

    def transcript(self) -> list[dict]:
        """Current blocks — rehydration of a client that connects mid-conversation."""
        return self._chat.transcript()
