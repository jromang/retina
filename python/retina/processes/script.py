"""The ``Script`` process — a script execution, turned into a replayable object.

An instance encapsulates the parameters exported by the script being executed; scripts can be
part of a view's processing history, on the same footing as a process instance defined by a
module. They can be undone and redone, stored in ProcessContainers, and manipulated like
process icons.

This is what was missing for pillar #1 (everything is scriptable) to meet pillar #4
(everything is replayable): a script modified views without anyone being able to say *with
which settings*, nor to replay it other than by launching it again by hand.

# What the instance remembers, and why

The **path** of the file and the **exported values** — not the code. A script is a document
that lives its own life; freezing it in the instance would give a copy that would silently
diverge. What we do retain is a **digest** of the file at the time it was saved: on replay, if
it no longer matches, we say so. A digest of this kind is sometimes used to *authenticate*
signed code; ours only serves to avoid lying about what is going to be executed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.parameters import ParameterContext, current, set_context
from ..process.registry import register


def file_digest(path: str) -> str:
    """SHA-256 digest of the file, or an empty string if it is unreadable."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


@register
class Script(Process):
    """Execution of a Python script, with the parameters it exported.

    This instance is not built by hand: it is born from an ``app.run_recipe`` whose script
    called ``retina.parameters.set(...)``. It is replayed, on the other hand, like any other
    process — by dropping it onto a view, or as a step of a recipe.
    """

    process_id = "Script"
    category = "Scripting"
    # The script does what it wants: it can change the geometry, open windows, touch nothing.
    # None of the optimizations that assume a pixel-by-pixel transformation apply.
    is_maskable = False
    supports_realtime = False
    parameters = [
        Parameter("path", "path", "", label=N_("File"),
                  tooltip=N_("Script executed — it does the work, not this instance")),
        # Named `exported_values` and not `values`: a parameter installs itself as an instance
        # attribute, and `values` would have shadowed the **method** `Process.values()`. That
        # was the case, and it made every Script instance unserializable — no library, no
        # recipe, no project, no echo — that is, exactly what this process promises. The old
        # key remains accepted at construction (see `__init__`).
        Parameter("exported_values", "str", "{}", label=N_("Parameters"),
                  tooltip=N_("JSON of the parameters exported by the script (retina.parameters)")),
        Parameter("digest", "str", "", label=N_("Digest"),
                  tooltip=N_("SHA-256 of the file when saved; checked on replay")),
    ]

    #: Serialization key from before the rename — an instance already stored in a library must
    #: keep on being readable. The meaning has not changed, only the name.
    _LEGACY_KEYS = {"values": "exported_values"}

    def __init__(self, **kwargs):
        for previous, new_item in self._LEGACY_KEYS.items():
            if previous in kwargs and new_item not in kwargs:
                kwargs[new_item] = kwargs.pop(previous)
        super().__init__(**kwargs)

    # --- exported values ------------------------------------------------------
    def exported(self) -> dict:
        """Remembered parameters. Unreadable JSON → empty dictionary, not an error."""
        try:
            data = json.loads(self.exported_values or "{}")
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    # --- execution ------------------------------------------------------------
    def execute_on(self, view) -> bool:
        """Replays the script on a view, with its parameters, as one history entry."""
        return self._run(view, view.begin_process, view.end_process, view.abort_process)

    def execute_global(self, app) -> bool:
        """Replays the script outside of any view — the global context."""
        self._execute(None)
        return True

    def _run(self, view, begin, end, abort) -> bool:
        begin(self._describe(), process=self)
        try:
            self._execute(view)
        except BaseException:
            # The bracket is purged: a view half processed by an interrupted script would be
            # worse than a clean failure, since nothing would state its contents.
            abort()
            raise
        end()
        return True

    def _execute(self, view) -> None:
        from ..process import context

        if current() is not None:
            # The established limit ("Attempt to execute a Script instance recursively").
            # Without it, a script that replays itself loops forever, and the parameter
            # context of the parent would be overwritten.
            raise RuntimeError(
                _t("Script: recursive execution — an instance cannot replay itself "
                   "from a script already running.")
            )
        path = str(self.path)
        if not path:
            raise ValueError(_t("Script: no file to execute."))
        if self.digest and file_digest(path) != self.digest:
            # Warn, do not refuse: the script may very well have been corrected deliberately.
            # Staying silent, on the other hand, would execute something other than what was
            # saved.
            print(
                f"* The script {Path(path).name} has changed since this instance "
                f"was saved."
            )

        app = context.get_application()
        if app is None:  # pragma: no cover — there is always at least the singleton
            raise RuntimeError(_t("Script: no application to execute the file."))

        set_context(ParameterContext(values=self.exported(), target_view=view, replaying=True))
        try:
            app.run_recipe(path)
        finally:
            set_context(None)

    def _apply(self, data):  # pragma: no cover — never reached
        raise RuntimeError(_t("Script does not transform pixels: it executes a file."))

    def __repr__(self) -> str:
        return f"Script({Path(str(self.path)).name!r})"
