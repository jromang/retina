"""``pipeline`` tool — automated preprocessing driven by an agent.

# Why a single entry point with several actions

Preprocessing is a sequence: ``scan`` (what does this folder hold?), ``plan`` (what are we
going to do?), ``run`` (do it), with ``survey`` and ``measures`` to inspect in between. Seven
separate tools would take up seven times the room in the agent's context to describe a chain
it has to follow in order anyway.

# Why handles

The ``pipeline.*`` handlers route inventory and plan **through the client**: that is the right
choice for the web shell, which displays and corrects them. An inventory of three hundred
frames is several hundred kilobytes of JSON — passing it to a language model would saturate
its context with data it does not have to read line by line. We therefore keep the object on
the server side and return only a handle (``inv1``, ``plan1``) along with a readable summary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .session_tools import await_job
from .tools import Tool, ToolError, _schema, _str

if TYPE_CHECKING:
    from .tools import ToolRegistry


def tools(registry: ToolRegistry) -> list[Tool]:
    server = registry.server
    handles = registry.handles

    async def pipeline(
        action: str,
        path: str | None = None,
        inventory: str | None = None,
        plan: str | None = None,
        preset: str = "auto",
        output_dir: str | None = None,
        group: str | None = None,
        paths: list[str] | None = None,
        recursive: bool = True,
    ) -> dict:
        pipe = server.pipeline_handlers

        if action == "presets":
            return {"presets": pipe.presets()}

        if action == "scan":
            if not path:
                raise ToolError("pipeline(action='scan') requires a path")
            found = await pipe.scan(path, recursive)
            key = handles.put("inv", found)
            return {"inventory": key, **_inventory_summary(found)}

        if action == "survey":
            found = handles.get(_require(inventory, "inventory"), "inv")
            return _survey_summary(pipe.survey(found))

        if action == "exclude":
            found = handles.get(_require(inventory, "inventory"), "inv")
            corrected = pipe.exclude(found, list(paths or []), True)
            handles.replace(inventory, corrected)  # type: ignore[arg-type]
            return {"inventory": inventory, **_inventory_summary(corrected)}

        if action == "plan":
            found = handles.get(_require(inventory, "inventory"), "inv")
            built = pipe.plan(found, preset, output_dir)
            key = handles.put("plan", built)
            return {"plan": key, **_plan_summary(built)}

        if action == "measures":
            built = handles.get(_require(plan, "plan"), "plan")
            measured = pipe.measures(built)
            # Per-frame measurements are bulky; the per-group summary is what serves to
            # decide. The details stay readable through execute_python if need be.
            return {"summary": measured["summary"], "rejects": measured["rejects"],
                    "criteria": measured["criteria"]}

        if action == "set_rejects":
            built = handles.get(_require(plan, "plan"), "plan")
            if not group:
                raise ToolError("pipeline(action='set_rejects') requires a group")
            corrected = pipe.set_rejects(built, group, list(paths or []))
            handles.replace(plan, corrected)  # type: ignore[arg-type]
            return {"plan": plan, "group": group, "rejected": len(paths or [])}

        if action == "run":
            built = handles.get(_require(plan, "plan"), "plan")
            reply = pipe.run(built)
            job = await await_job(server, reply["job"])
            return {"job": job["id"], "state": job["state"],
                    "message": job["message"], "report": job["result"]}

        if action == "report":
            return {"report": pipe.report()}

        raise ToolError(
            f"Unknown action: {action!r} "
            "(presets, scan, survey, exclude, plan, measures, set_rejects, run, report)"
        )

    return [
        Tool(
            name="pipeline",
            description=(
                "Automated pre-processing of a folder of raw sub-exposures — the equivalent "
                "of PixInsight's WBPP: calibration, cosmetic correction, registration and "
                "integration, file to file, with caching and resume.\n"
                "Run the actions in order: 'scan' a folder (returns an inventory handle), "
                "'survey' to see the detected groups and matched masters, 'plan' to build "
                "the execution plan (handle), then 'run'. 'measures' and 'set_rejects' let "
                "you drop bad frames after measurement; 'exclude' removes files from the "
                "project entirely (wrong type, corrupt, wrong target) — that is a different "
                "thing and it invalidates calibration caches.\n"
                "Inventories and plans stay on the server: pass the handle, not the data."
            ),
            input_schema=_schema(
                {
                    "action": _str(
                        "presets | scan | survey | exclude | plan | measures | set_rejects "
                        "| run | report",
                        ("presets", "scan", "survey", "exclude", "plan", "measures",
                         "set_rejects", "run", "report"),
                    ),
                    "path": _str("Folder of raw frames, for action='scan'."),
                    "inventory": _str("Inventory handle from a previous scan, e.g. 'inv1'."),
                    "plan": _str("Plan handle from a previous plan, e.g. 'plan1'."),
                    "preset": _str("Plan preset (see action='presets'); default 'auto'."),
                    "output_dir": _str("Where products are written; defaults to "
                                       "<folder>/retina_pipeline."),
                    "group": _str("Group key, for set_rejects."),
                    "paths": {"type": "array", "items": {"type": "string"},
                              "description": "File paths, for exclude/set_rejects."},
                    "recursive": {"type": "boolean", "description": "Recurse when scanning.",
                                  "default": True},
                },
                ("action",),
            ),
            handler=pipeline,
            mutating=True,
        ),
    ]


def _require(value: str | None, what: str) -> str:
    if not value:
        raise ToolError(f"This action requires a {what} handle")
    return value


def _inventory_summary(data: dict) -> dict:
    """What an operator looks at after a scan: how much of what, and which anomalies.

    We go back through :class:`Inventory` rather than recounting by hand: ``counts`` and OSC
    detection are domain rules, and replaying them here would make them diverge.
    """
    from ...pipeline.scan import Inventory

    inventory = Inventory.from_dict(data)
    counts = inventory.counts()
    summary: dict = {
        "root": inventory.root,
        "frames": sum(counts.values()),
        "by_kind": counts,
    }
    excluded = sum(1 for f in inventory.frames if getattr(f, "excluded", False))
    if excluded:
        summary["excluded"] = excluded
    if inventory.is_osc:
        summary["osc"] = True
        summary["bayer_pattern"] = inventory.bayer_pattern
    return summary


def _survey_summary(data: dict) -> dict:
    """Detected groups and paired masters — one line per group, without the frames."""
    matches = data.get("matches", {})
    groups = []
    for entry in data.get("groups", []):
        key = entry.get("key")
        group = {
            "key": key,
            "kind": entry.get("kind"),
            "frames": entry.get("count"),
            "filter": entry.get("filter"),
            "exposure": entry.get("exposure"),
            "binning": entry.get("binning"),
            "gain": entry.get("gain"),
        }
        match = matches.get(key)
        if match is not None:
            group["calibration"] = {
                "bias": match.get("bias"),
                "dark": match.get("dark"),
                "flat": match.get("flat"),
                "dark_scale": match.get("dark_scale"),
            }
            if match.get("notes"):
                group["notes"] = match["notes"]
        groups.append(group)
    return {"groups": groups}


def _plan_summary(data: dict) -> dict:
    """The plan on one page: what will be done, where, and what it will weigh on disk."""
    steps = [
        {"id": step.get("id"), "kind": step.get("kind"), "label": step.get("label"),
         "group": step.get("group")}
        for step in data.get("steps", [])
    ]
    return {
        "steps": len(steps),
        "outline": steps,
        "output_dir": data.get("output_dir"),
        "disk": data.get("disk"),
        "notes": data.get("notes", []),
        "products": [
            {"key": p.get("key"), "frames": p.get("frames"), "path": p.get("path")}
            for p in data.get("products", [])
        ],
    }


__all__ = ["tools"]
