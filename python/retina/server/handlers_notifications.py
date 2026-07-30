"""``notifications.*`` family of the protocol.

Thin facades over ``app.notifications``: the gesture goes through the domain (hence with an
echo for ``dismiss``/``clear``), and broadcasting is the business of the ``on_changed`` hook
that the shell wires up in ``core.py``. No method is marked mutating: the hook already does
``notify`` + ``mark_state_dirty``, including when the gesture comes from the console — a
mutating flag would rebroadcast the snapshot twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..app import Application

NOTIFICATION_METHODS: dict[str, bool] = {
    "notifications.list": False,
    "notifications.dismiss": False,
    "notifications.clear": False,
}


class NotificationHandlers:
    def __init__(self, app: Application) -> None:
        self._app = app

    def list(self) -> list[dict]:
        """The whole center, most recent first (the snapshot already carries it)."""
        return [n.to_dict() for n in self._app.notifications]

    def dismiss(self, id: str) -> bool:
        return self._app.notifications.dismiss(id)

    def clear(self) -> None:
        self._app.notifications.clear()
