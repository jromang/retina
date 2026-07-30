---
id: ImageIdentifier
category: Image
title: Image Identifier
brief: Renames the target view/window by changing its identifier (id) in a scriptable way.
keywords: [identifier, rename, id, window, view, metadata, console]
related: [FITSHeader, NewImage, SampleFormatConversion]
icon: id
references:
  - "PixInsight — ImageIdentifier process reference."
  - "PJSR — ImageWindow.mainView.id / View.id."
---

## Summary

`ImageIdentifier` is a utility process that **renames** a view: it replaces its identifier
(`view.id`) — and, if the view is a window's main view, the window's identifier (`window.id`)
too — with the supplied value. It is the scriptable equivalent of double-clicking a window's
name in PixInsight: no pixel data is touched, only the label used to address the view from the
console, from recipes, and from other process instances (`PixelMath`, `LRGBCombination`,
`ChannelCombination`…) changes.

## Use cases

- **Give an explicit name** to the result of a global operation (`Integration`, `NewImage`…)
  that receives a generic default identifier such as `Image01`.
- **Prepare stable identifiers** before a `PixelMath` expression or a channel combination that
  reference views by `id` (e.g. `L`, `R`, `G`, `B`, `Ha`, `OIII`).
- **Batch-rename** inside a recipe: iterate over a list of windows and assign each one an
  identifier derived from its filename or filter, reproducibly.
- **Clarify a console pipeline** by giving readable names (`master_dark`, `light_stacked`)
  instead of keeping the auto-generated identifiers.

## How it works

The process is a plain rename, executed via `execute_on(view)`:

1. If the `new_id` parameter is non-empty, `view.id` is replaced with its value.
2. If the view is attached to a window (`view.window is not None`), the window's identifier
   (`window.id`) is updated to the same name, keeping it consistent with the main view.
3. If `new_id` is empty, the operation is a no-op: the current identifier is kept as is.

Unlike processes that transform pixels, `ImageIdentifier` pushes **no image history entry**
(`begin_process()/end_process()` do not wrap a data modification): it is a pure metadata change,
and it is not maskable (`is_maskable = False`) since there is nothing to mask. Applied without a
view (`execute_on_image`), it does nothing — a bare `Image`, detached from any window, has no
identifier to change.

## Mathematics

This process has no mathematical basis: it neither reads nor modifies pixel samples, it simply
rewrites a string used as the addressing key for the view and its window. There is therefore no
transform, statistic, or kernel to document here.

## Parameters

- **`new_id`** — *str*, default `""`. New identifier to assign to the view (and to the
  associated window, if any). An empty string leaves the identifier unchanged (no-op) rather
  than clearing the name.

## Tips & pitfalls

> **Warning** — Retina does not enforce unique identifiers: renaming two windows to the same
> `new_id` does not raise an error, but it makes later lookups by `id` ambiguous (in the
> console, in `PixelMath`, in a recipe replayed later). Check `app.windows` first to make sure
> the name isn't already taken.

- An empty identifier does not clear the name: this is deliberately a no-op, to avoid losing
  track of a window because of a scripting mistake.
- Because the change opens no image history entry, `undo()`/`redo()` on the view do not revert
  a rename: handle naming upfront rather than relying on undo to fix a bad `id` choice.
- In the console, the Python echo of this action (`ImageIdentifier(new_id=...).execute_on(view)`)
  is the simplest way to automate consistent naming across a whole processing recipe.

## See also

- [FITSHeader](retina-doc://FITSHeader) — writes a FITS keyword on the target window, another
  metadata-only process with no effect on pixels.
- [NewImage](retina-doc://NewImage) — creates a blank or filled window, which is often assigned
  an explicit identifier right afterward via `ImageIdentifier`.
- [SampleFormatConversion](retina-doc://SampleFormatConversion) — another technical utility in
  the `Image` module, except it operates on samples rather than metadata.

## References

- PixInsight — *ImageIdentifier* process reference.
- PJSR — *ImageWindow.mainView.id* / *View.id*.
