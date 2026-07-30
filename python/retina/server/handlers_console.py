"""``console.*`` family — the Python REPL exposed to the frontend.

Execution goes off to the console's dedicated thread; the handler ``await``s its result
without blocking the loop, which stays free to broadcast standard output, the echo of actions
and progress while a script runs.

``console.execute`` is marked **mutating**: a script may have opened windows, applied
processes, changed the active view. Rather than hoping to guess what it touched, we
rebroadcast the complete snapshot — the same reasoning as for the rest of the protocol.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .console import Console

CONSOLE_METHODS: dict[str, bool] = {
    "console.execute": True,
    "console.complete": False,
    "console.inspect": False,
    "console.interrupt": False,
    "console.history": False,
}


class ConsoleHandlers:
    def __init__(self, console: Console) -> None:
        self._console = console

    async def execute(self, code: str) -> dict:
        """Executes Python code in the same process as ``app``."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._console.executor, self._console.execute, code)

    async def complete(self, code: str, cursor_pos: int | None = None) -> dict:
        """Completions at the cursor position.

        Goes through the same executor as ``execute``: completion touches the shell's state,
        and serializing it avoids reaching into that state while a cell runs. Accepted
        consequence — during a long script, completion waits, exactly as in qtconsole.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._console.executor, self._console.complete, code, cursor_pos
        )

    async def inspect(self, code: str, cursor_pos: int | None = None) -> dict:
        """Documentation for the object under the cursor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._console.executor, self._console.inspect, code, cursor_pos
        )

    def interrupt(self) -> bool:
        """Interrupts the running execution (equivalent to Ctrl+C).

        **Does not go through the executor**: that one is busy with the cell to interrupt.
        The call is therefore made from the loop, and raises the exception in the console
        thread.
        """
        return self._console.interrupt()

    async def history(self, limit: int = 100) -> list[str]:
        """Previous entries of the session (persisted across launches)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._console.executor, self._console.history, limit)
