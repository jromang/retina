"""``preferences.*`` family of the protocol.

Thin facades over ``app.preferences``: the gesture goes through the domain — hence with an
echo, hence learnable — and broadcasting is the business of the ``on_changed`` hook that
``core.py`` wires up. No method is marked mutating: the hook already sends the notification,
including when the setting comes from the console. A mutating flag would rebroadcast the
snapshot for nothing, preferences not being in it.

``describe`` reuses :func:`~retina.server.handlers_process._parameter` as is: it is the same
projection as for a process parameter, hence the **same auto-generated form** on the client
side. Labels are translated there, as everywhere, at the edge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..i18n import translate
from .handlers_process import _parameter

if TYPE_CHECKING:
    from ..app import Application

PREFERENCE_METHODS: dict[str, bool] = {
    "preferences.describe": False,
    "preferences.get": False,
    "preferences.set": False,
    "preferences.reset": False,
}


class PreferenceHandlers:
    def __init__(self, app: Application) -> None:
        self._app = app

    def describe(self) -> list[dict]:
        """The full schema, group by group, with the current values."""
        return [
            {
                "id": group["id"],
                "label": translate(group["label"]),
                "parameters": [
                    {**_parameter(entry["parameter"]), "value": entry["value"]}
                    for entry in group["parameters"]
                ],
            }
            for group in self._app.preferences.describe()
        ]

    def get(self, key: str | None = None) -> Any:
        if key is None:
            return self._app.preferences.all()
        return self._app.preferences.get(key)

    def set(self, key: str, value: Any) -> Any:
        return self._app.preferences.set(key, value)

    def reset(self, key: str | None = None) -> None:
        self._app.preferences.reset(key)
