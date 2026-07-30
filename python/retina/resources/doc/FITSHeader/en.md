---
id: FITSHeader
category: Image
title: FITS Header
brief: Adds, edits, or comments a FITS keyword in the target window's metadata.
keywords: [FITS, header, keyword, metadata, card, HIERARCH]
related: [ImageIdentifier, NewImage, SampleFormatConversion]
icon: file-info
references:
  - "PixInsight — FITSHeader tool reference."
  - "Pence, W. et al. — Definition of the Flexible Image Transport System (FITS), version 3.0."
  - "astropy.io.fits — Header cards and keyword conventions."
---

## Summary

`FITSHeader` writes a **keyword**, its value, and an optional comment into the target window's
`window.keywords` dictionary — the FITS metadata attached to the image, distinct from its
pixels. It is a **technical utility** process in the PixInsight sense (category `Image`,
alongside `NewImage`, `ImageIdentifier`, `SampleFormatConversion`): it performs no numeric
operation on the image, it annotates or fixes the header that `save_fits` later writes to disk.
Unlike keywords loaded from an existing FITS file (auto-typed by astropy as int, float,
bool, …), any value written by this process stays a **plain string**.

## Use cases

- Add a missing keyword after processing (e.g. `OBJECT`, `TELESCOP`, `FILTER`) when the source
  file didn't carry it.
- Fix an incorrect keyword before integration (e.g. an `EXPTIME` misreported by the acquisition
  software).
- Document the applied processing in the header, via a custom keyword, to trace a recipe inside
  the output file.
- Inject synthetic keywords consumed downstream by other processes or scripts (e.g. a session
  or filter identifier read back by an automated sorting script).

## How it works

The process never touches pixels: `execute_on_image` is a no-op that returns the `Image`
unchanged, since keywords live on `ImageWindow`, not on `Image`. The real operation happens in
`execute_on(view)`:

1. If `keyword` is empty, or the view has no associated window (`view.window is None`), nothing
   is written; the process still returns success (`True`) silently.
2. Otherwise, `view.window.keywords[keyword]` is set to `value` alone, or to the tuple `(value,
   comment)` when `comment` is non-empty — the convention used by `astropy.io.fits.Header` to
   carry a FITS card comment.
3. Since `window` is shared by the main view and all of its previews, the write applies to the
   **entire image header**, never to a single preview.

The write stays in memory in `window.keywords` until a `save_fits(path, image,
window.keywords)` call, which copies every entry into the astropy `Header` before writing to
disk.

## Mathematics

Purely a metadata process: no numeric transformation of pixels is involved, so no formula
applies here.

## Parameters

- **`keyword`** — *str*, default `""`. FITS keyword name (e.g. `OBJECT`, `FILTER`). FITS
  standard: 8 characters max, uppercase; beyond that, `astropy` requires the `HIERARCH`
  convention. An empty value disables the process (no-op).
- **`value`** — *str*, default `""`. Value associated with the keyword, always stored as a
  string — even if it represents a number.
- **`comment`** — *str*, default `""`. Optional comment for the FITS card. Left empty, only the
  value is stored (no tuple).

## Tips & pitfalls

> **Warning** — `value` is always stored as a plain string. An existing numeric keyword loaded
> from a FITS file (e.g. `EXPTIME` as a `float`) will turn back into a **string** card after
> passing through `FITSHeader`, which can confuse downstream tools expecting a numeric type.

> **Note** — follow the FITS standard for `keyword`: uppercase, 8 characters maximum. A longer
> or lowercase name may be rejected or misinterpreted by `astropy` on write.

- The process updates `window.keywords` immediately, but nothing is written to disk until a
  `save_fits` call is executed.
- Applied from a preview, the write affects the whole window's header (previews have no FITS
  metadata of their own).
- To read a value rather than write it, inspect `view.window.keywords[...]` directly from the
  console — there is no dedicated read process.

## See also

- [ImageIdentifier](retina-doc://ImageIdentifier) — renames the window's internal identifier.
- [NewImage](retina-doc://NewImage) — creates a blank window to annotate.
- [SampleFormatConversion](retina-doc://SampleFormatConversion) — another technical utility from
  the same module.

## References

- PixInsight — *FITSHeader* tool reference.
- Pence, W. et al. — *Definition of the Flexible Image Transport System (FITS)*, version 3.0.
- astropy.io.fits — *Header* cards and keyword conventions.
