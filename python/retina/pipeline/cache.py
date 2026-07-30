"""Run cache: do not recompute what is already right.

A pre-processing run is relaunched often — a night of lights is added, a rejection threshold
is changed, the computer shuts down halfway through. Recomputing thirty masters every time
is the main irritant of a badly done batch pre-processing.

Each output is therefore accompanied by a **manifest** ``<output>.manifest.json`` describing
what produced it: identity of the inputs and parameters of the processes. The step is
skipped if the manifest matches exactly what we are about to do again.

# What makes up the fingerprint

Paths of the inputs, their size and their modification date (to the nanosecond), plus the
values of every process of the step. **Not** the content of the pixels: hashing 300 files of
50 Mpx would cost more than recomputing. It is the usual trade-off, and it has the same
consequence — touching a file without modifying it invalidates the cache. The remedy is
``force=True``, not a content hash.

The values retained are those of :meth:`Process.cache_values`, and not all of them: a
process may declare that a given parameter does not change its output file. The frame
selector depends on it — its approval expressions and its manual rejections are re-evaluated
at each run at zero cost, whereas re-invalidating the measurement step would make one pay
again for star detection on every sub of the group.

# The order of writing is not a detail

The manifest is written **after** the output, and the output itself is written in two steps
(temporary file then ``os.replace``, atomic on the same file system). An interruption —
crash, cancellation — therefore leaves either a complete state or nothing: never a truncated
output that the cache would declare valid on the next run.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .plan import PlanStep

CACHE_VERSION = "1"
MANIFEST_SUFFIX = ".manifest.json"


def _identity(path: str) -> dict:
    """Identity of an input file: what changes when it changes."""
    try:
        stat = os.stat(path)
    except OSError:
        return {"path": path, "missing": True}
    return {"path": path, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _digest(path: str) -> str:
    """Digest of the content of a hook script — an unreadable file returns an empty string,
    which is stable: the hook will fail at run time, not here."""
    from ..processes.script import file_digest

    return file_digest(path)


def fingerprint(step: PlanStep, resolved: dict | None = None) -> str:
    """Fingerprint of what the step is going to produce, inputs and parameters included.

    ``resolved`` carries the late bindings once they are known (reference, weights): without
    them, changing reference frame would not re-invalidate the registrations.
    """
    payload = {
        "version": CACHE_VERSION,
        "step": step.id,
        "kind": step.kind,
        "inputs": [_identity(p) for p in step.inputs],
        "processes": [{"process_id": p.process_id, "values": p.cache_values()}
                      for p in step.processes],
        "resolved": resolved or {},
    }
    # Hooks enter the fingerprint **by their content**: an edited script must replay the
    # step, failing which one would believe its new version applied. The key is added only
    # if there are any, so that manifests written before stay valid.
    if step.hooks:
        payload["hooks"] = {phase: {"path": path, "digest": _digest(path)}
                            for phase, path in sorted(step.hooks.items())}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=repr)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def manifest_path(output: str) -> str:
    return output + MANIFEST_SUFFIX


def is_fresh(step: PlanStep, resolved: dict | None = None) -> bool:
    """True if every output exists and carries the expected fingerprint."""
    if not step.outputs:
        return False  # a step without an output (the measurements) always replays
    digest = fingerprint(step, resolved)
    for output in step.outputs:
        if not os.path.exists(output):
            return False
        try:
            with open(manifest_path(output), encoding="utf-8") as fh:
                if json.load(fh).get("fingerprint") != digest:
                    return False
        except (OSError, ValueError):
            return False
    return True


def write_manifest(step: PlanStep, output: str, resolved: dict | None = None) -> None:
    """Seals an output. To be called **after** writing it, never before."""
    data = {
        "fingerprint": fingerprint(step, resolved),
        "step": step.id,
        "label": step.label,
        "inputs": list(step.inputs),
        "output": output,
    }
    with open(manifest_path(output), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def save_atomic(path: str, write: Callable[[str], None]) -> None:
    """Writes via a temporary in the same folder then replaces — never a truncated output.

    ``write`` receives the temporary path. The rename is atomic as long as source and
    destination share the file system, hence the temporary *next to* the target.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.part"
    try:
        write(temporary)
        os.replace(temporary, path)
    except BaseException:
        # including ProcessCancelled and KeyboardInterrupt: leave nothing behind
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def clear(output_dir: str) -> int:
    """Deletes every manifest under ``output_dir``. Returns the number erased."""
    cleared = 0
    for current, _, files in os.walk(output_dir):
        for name in files:
            if name.endswith(MANIFEST_SUFFIX):
                os.remove(os.path.join(current, name))
                cleared += 1
    return cleared
