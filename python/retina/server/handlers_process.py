"""``process.*`` family — the process catalogue exposed to the frontend.

The frontend codes **no** form: it generates them from the ``Parameter`` schema. That is what
lets the 115 processes (and those a third-party package will add by entry-point) have an
interface without writing a line of UI per process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .rpc import DOMAIN_ERROR, RpcError

if TYPE_CHECKING:
    from .jobs import JobRunner

PROCESS_METHODS: dict[str, bool] = {
    "process.list": False,
    "process.get": False,
    # `run` returns a job id immediately; the snapshot goes out at the *end* of the job,
    # not here.
    "process.run": False,
    "process.run_container": False,
    # serializations of a recipe — pure reads
    "process.container_source": False,
    "process.container_xml": False,
    "process.container_from_xml": False,
    "process.cancel": False,
    "process.jobs": False,
}


def _jsonable(value: Any) -> Any:
    """Makes a parameter value serializable.

    Defaults are Python literals — including tuples for point lists, which ``json`` refuses as
    keys but accepts as values in list form.
    """
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parameter(param, choices=None) -> dict:
    """One parameter, as the auto-generated form will receive it.

    It is **here** that the labels are translated, and not in the domain: ``Parameter.label``
    carries an English msgid, written once and for all at the class definition, whereas the
    language can change during a session. Three intended consequences:

    * the console sees English — a process's code is code, it does not change language;
    * a **third-party** process without a catalogue stays usable: ``gettext`` returns the
      msgid, so the user reads English rather than a technical key;
    * ``process.list`` needs no ``lang`` argument: the server translates into *its* effective
      language, which the client adopts (cf. ``web/src/shell/locale.ts``).

    Enumeration ``choices`` are **not** translated: they are domain values, serialized as is
    in instances and projects.
    """
    from ..i18n import translate

    # Dynamic choices (supplied by the class) win over the descriptor's static ones.
    effective = choices if choices is not None else param.choices
    visible = None
    if param.visible_when is not None:
        controller, values = param.visible_when
        visible = {"param": controller, "values": [_jsonable(v) for v in values]}
    return {
        "id": param.id,
        "type": param.type,
        "default": _jsonable(param.default),
        "min": param.min,
        "max": param.max,
        "choices": list(effective) if effective else None,
        "label": translate(param.label) if param.label else param.id,
        "tooltip": translate(param.tooltip) if param.tooltip else "",
        "visible_when": visible,
    }


def _describe(cls) -> dict:
    from ..documentation import has_doc, icon_name

    return {
        "process_id": cls.process_id,
        "category": cls.category,
        "is_global": bool(cls.is_global),
        "is_maskable": bool(getattr(cls, "is_maskable", False)),
        "creates_window": bool(getattr(cls, "creates_window", False)),
        # effective value (excludes globals and window generators): the client does not have
        # to recombine three flags to know whether it can offer the preview
        "supports_realtime": cls.realtime_capable(),
        "has_doc": has_doc(cls.process_id),
        "icon": icon_name(cls.process_id),
        "parameters": [_parameter(p, cls.parameter_choices(p.id)) for p in cls.parameters],
    }


class ProcessHandlers:
    def __init__(self, runner: JobRunner) -> None:
        self._runner = runner

    def list(self) -> list[dict]:
        """Full catalogue: parameter schema, category, icon, capabilities."""
        from ..process.registry import all_processes

        return [_describe(cls) for cls in all_processes().values()]

    def get(self, process_id: str) -> dict:
        """Description of a single process."""
        from ..process.registry import get

        return _describe(get(process_id))

    def run(
        self, process_id: str, params: dict | None = None, view: str | None = None
    ) -> dict:
        """Starts a process in the background and returns its job id.

        Returns **immediately**: stacking fifty frames must not leave the interface
        unresponsive. The rest arrives through notifications (``job.progress``, ``job.done``…),
        then through a snapshot.
        """
        from ..process.registry import get

        cls = get(process_id)
        try:
            instance = cls(**(params or {}))
        except TypeError as exc:
            raise RpcError(DOMAIN_ERROR, f"{process_id}: invalid parameter — {exc}") from None

        if view is None and not cls.is_global and self._runner.needs_active_view():
            raise RpcError(DOMAIN_ERROR, f"{process_id}: no target view")

        return {"job": self._runner.submit(instance, process_id, view)}

    def run_container(
        self, processes: list[dict], view: str | None = None, name: str | None = None
    ) -> dict:
        """Runs a whole recipe — **one** job, in order, **one** echo.

        Dropping a recipe used to start one independent job per step: nothing guaranteed the
        order (the pool has four threads), and the console received N lines instead of the
        recipe. Yet the order is the very meaning of a pipeline — stretching then denoising
        is not denoising then stretching.

        Nothing to add on the domain side: ``app.apply`` already accepts a
        :class:`ProcessContainer` and echoes its source, and ``JobRunner`` passes the object
        through as is. Only the network door was missing.
        """
        from ..process.container import ProcessContainer

        if not processes:
            raise RpcError(DOMAIN_ERROR, "empty recipe")
        try:
            container = ProcessContainer.from_dicts(processes)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise RpcError(DOMAIN_ERROR, f"unreadable process: {exc}") from None

        # A global process does not apply to a view: `execute_on` would fail in the middle of
        # the recipe, after having already modified the image. Better to refuse before
        # starting. Disabled steps escape this: they will not run.
        globals_found = [
            p.process_id
            for i, p in enumerate(container.processes)
            if container.enabled(i) and getattr(p, "is_global", False)
        ]
        if globals_found:
            raise RpcError(
                DOMAIN_ERROR,
                f"global process in a recipe: {', '.join(globals_found)}",
            )

        if view is None and self._runner.needs_active_view():
            raise RpcError(DOMAIN_ERROR, "recipe: no target view")

        return {"job": self._runner.submit(container, name or repr(container), view)}

    def container_source(self, processes: list[dict]) -> str:
        """Recipe as Python source — enough to replay it, edit it, comment it.

        The equivalent elsewhere is an "Instance Source Code" command (JavaScript or XPSM).
        `ProcessContainer.to_python_source` already existed and nothing exposed it: a recipe
        could be run, never read.
        """
        return self._container(processes).to_python_source("app.active_view")

    def container_xml(self, processes: list[dict]) -> str:
        """Recipe in XML form — our equivalent of the `.xpsm` interchange format."""
        return self._container(processes).to_xml()

    def container_from_xml(self, text: str) -> list[dict]:
        """Reads an XML recipe back and returns its wire form."""
        from ..process.container import ProcessContainer

        try:
            return ProcessContainer.from_xml(text).to_dicts()
        except Exception as exc:
            raise RpcError(DOMAIN_ERROR, f"unreadable recipe: {exc}") from None

    def _container(self, processes: list[dict]):
        from ..process.container import ProcessContainer

        try:
            return ProcessContainer.from_dicts(processes)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise RpcError(DOMAIN_ERROR, f"unreadable process: {exc}") from None

    def cancel(self, job: str) -> bool:
        """Requests the cancellation of a job.

        Cooperative: it takes effect at the next checkpoint. Long processes place them in
        their loops; the others finish first. See ``server/jobs.py``.
        """
        return self._runner.cancel(job)

    def jobs(self) -> list[dict]:
        """Running jobs (queued + executing)."""
        return self._runner.active()
