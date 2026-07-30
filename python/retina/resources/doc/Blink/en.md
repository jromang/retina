---
id: Blink
category: ImageInspection
title: Blink
brief: Scrolls through a sequence of frames with quick per-frame statistics, for visual triage of subs.
keywords: [blink, inspection, triage, sequence, scrolling, quick statistics, sub selection]
related: [SubframeSelector, Statistics, ImageIdentifier, CosmeticCorrection]
icon: eye
references:
  - "PixInsight — Blink process reference."
---

## Summary

`Blink` is the **headless core of the sequence inspector**: it loads a list of files, computes a
few quick statistics for each one (median, min, max, dimensions), and lets you navigate from
frame to frame through a current index. It is the scriptable equivalent of PixInsight's "Blink"
panel, which scrolls through a stack of subs for visual triage — here all the loading and
navigation logic is testable without Qt; a GUI panel only needs to display `current_image()` and
call `step()`.

## Use cases

- **Sort a batch of subs** before calibration: spot blurred, cloudy, satellite/plane-trailed, or
  tracking-shaken exposures.
- **Visually review a session** by flicking rapidly through the views, film-strip style.
- **Prepare automated triage** by leaning on the per-frame statistics (`median`, `min`, `max`) as
  a first pass before more thorough filtering with `SubframeSelector`.
- **Check the geometric consistency** of a stack (same `shape`) before integration.

## How it works

`load()` iterates over the `frames` list, loads each file through the generic image loader
(FITS, XISF, TIFF/PNG/JPEG, RAW…), converts it to `float32`, and computes a small statistics
dictionary for each one: median, minimum, maximum, and `(H, W, C)` shape. These dictionaries are
accumulated in `self.stats`, in file order, and the current index is reset to 0.

`current_image()` returns the `Image` at the current index (loading the sequence first if it
hasn't been loaded yet). `step(delta)` moves the current index by `delta` positions, **wrapping
around** (modulo the sequence length): `step(1)` advances one frame, `step(-1)` goes back, and
the index never runs outside the list's bounds.

As a **global** process (`is_global = True`), `execute_global(app)` simply calls `load()` — it
does not create a new window (`creates_window = False`): Blink produces no output image, it
**inspects** an existing sequence. The actual scrolling experience (display, keyboard shortcuts,
thumbnail preview) is driven by the GUI, which relies solely on `current_image()` and `step()`.

## Mathematics

This process has no mathematical foundation of its own: it is an **inspection and navigation**
tool with no pixel transformation. The only computed quantities are elementary per-frame
statistics — median $\operatorname{med}(x)$, minimum $\min(x)$ and maximum $\max(x)$ over the
image's samples $x$ — used as quick triage landmarks, not as robust estimators feeding a
downstream algorithm (unlike the mad_std used by `Integration`, see
[Integration](retina-doc://Integration)).

## Parameters

- **`frames`** — *pathlist*, default `[]`. Sequence of file paths to load and scroll through
  (raw subs or any other stack of images of the same kind). The list order determines the
  navigation order.

## Tips & pitfalls

> **Warning** — `load()` loads the **entire sequence into memory** before computing statistics:
> on a very long series of full-resolution subs, this can consume a lot of RAM. For large
> batches, process in sub-groups instead.

- The per-frame `median`/`min`/`max` lets you spot at a glance an abnormally bright exposure
  (cloud, moon) or an abnormally dark one (shutter stuck, forgotten lens cap) without opening
  every image.
- Frames with a `shape` different from an otherwise homogeneous batch usually signal a wrong
  binning or an accidental crop — fix this before `StarAlignment`/`Integration`.
- `step()` wraps around the sequence: calling `step(1)` in a loop lets you sweep through the
  whole set without handling the bounds yourself.

## See also

- [SubframeSelector](retina-doc://SubframeSelector) — automated sub filtering/scoring (FWHM,
  detection threshold).
- [Statistics](retina-doc://Statistics) — detailed statistics on a single image.
- [ImageIdentifier](retina-doc://ImageIdentifier) — window identification/renaming.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — correction of defective pixels found
  during inspection.

## References

- PixInsight — *Blink* process reference.
