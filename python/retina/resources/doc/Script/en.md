---
id: Script
category: Scripting
title: Script
brief: A Python script execution, recorded as a process instance — undoable, storable in the library, and replayable inside a recipe.
keywords: [script, python, parameters, reproducibility, history, recipe, replay, digest]
related: [PixelMath, HistogramTransformation]
icon: file-code
references:
  - "PixInsight — Script process and the PJSR Parameters object."
  - "CLAUDE.md — pillars 1 (Python-first) and 4 (reproducibility)."
---

## Summary

`Script` is the process instance left behind by a Python script that **exported parameters**.
It transforms no pixels: it is a *replayable marker* that enters the view's history, can be
undone, stored as a library icon, and placed inside a recipe — exactly like any other process.

You do not build one by hand. It is born from an `app.run_recipe(path)` whose script called
`retina.parameters.set(...)` at least once.

## Use cases

- **Make a homemade treatment reproducible**: a script that denoises according to three
  settings can export them, and its execution becomes an object you replay on another frame
  with different values.
- **Mix scripts and processes in a recipe**: a `Script` step slots into a `ProcessContainer`
  between two catalog processes.
- **Undo a script**: the history entry lets you return to the previous state without having to
  know what the script did.
- **Keep a setting**: dragging the instance into the library puts aside the pair "this script,
  with these values".

## How it works

A script declares its settings through the `retina.parameters` object, the counterpart of
PJSR's `Parameters`:

```python
p = retina.parameters
threshold = p.get_real('threshold', 0.5)   # value from a replay, or the default
p.set('threshold', threshold)              # ← this is what makes the script replayable

from retina import Binarize
Binarize(threshold=threshold).execute_on(app.active_view)
```

At the end of execution, if — and only if — at least one parameter was exported, a `Script`
instance is pushed into the target view's history. Replaying the instance re-executes the file
with the stored values: the script then reads back its own settings through `get_real`,
`get_int`, `get_bool` or `get_str`.

A script can also query its target: `parameters.is_view_target`, `parameters.target_view`,
`parameters.is_global_target`.

## The rule that avoids duplication

A script that merely chains `app.apply(...)` calls leaves **no** `Script` instance. This is
deliberate, and it is PixInsight's rule: such a script has already produced a step-by-step
history, fully undoable and replayable; adding an entry that describes it a second time would
add nothing and would make undo ambiguous.

Exporting a parameter is therefore how a script declares: "my unit of work is me, not my
steps".

## Parameters

- **File** (`path`) — the executed script. It does the work; the instance is only its trace.
  The code is **not** copied into the instance: a script is a document that lives its own life,
  and freezing it would produce a copy that silently diverges.
- **Parameters** (`values`) — JSON of the exported values. Editing them and replaying means
  re-running the script with different settings.
- **Digest** (`digest`) — SHA-256 of the file at recording time.

## Tips & pitfalls

> **Warning** — if the file changed since recording, the replay **reports it** in the console
> but still runs: the script may well have been fixed on purpose. Staying silent, on the other
> hand, would execute something other than what was recorded.

- Recursive execution is refused: a `Script` instance cannot be replayed from a script that is
  already running. Without that limit, a script replaying itself would loop forever. PixInsight
  imposes the same restriction.
- The instance stores a **path**. Moving the file breaks replay — that is the price of not
  embedding the code.
- Outside script execution, `retina.parameters` is inert: writes are ignored and reads return
  their default. Calling a script's function from the console therefore never raises.

## See also

- [PixelMath](retina-doc://PixelMath) — the other doorway from Python into processing, for an
  expression rather than a file.
- [HistogramTransformation](retina-doc://HistogramTransformation) — a catalog process, of the
  kind a script calls.

## References

- PixInsight — *Script* process and the PJSR *Parameters* object.
- CLAUDE.md — pillars 1 (Python-first) and 4 (reproducibility).
