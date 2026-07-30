---
id: MosaicPlanner
category: Astrometry
title: Mosaic Planner
brief: Computes the pointings of a mosaic before acquiring it, and draws the coverage map.
keywords: [mosaic, planning, tiles, panels, overlap, framing, field of view, pointing]
related: [MosaicReproject, FindingChart, PlateSolve, SurveyReference]
icon: grid-4x4
references:
  - "Calabretta, M. R. & Greisen, E. W. (2002) — Representations of celestial coordinates in FITS, A&A 395, 1077 (TAN projection)."
---

## Summary

Everything Retina knew about mosaics until now looked **backwards**: `detect_panels` finds
the panels in frames you have already taken. `MosaicPlanner` goes the other way — give it a
target, your sensor's field and an overlap, and it returns the list of pointings to
programme, plus a map to check at a glance that the object is really covered.

Global process: it reads no image and produces a new window (the map), astrometrically
solved, so it overlays with everything else.

## Use cases

- Frame a **large object** (Andromeda, the Veil, the Rosette) that does not fit your sensor.
- Plan a **wide-field survey** of a region, with a controlled overlap.
- Check *before* the night whether 3×2 panels are enough, or whether 4×3 are needed.

## How it works

Tile centres are laid out in the **tangent plane** of the target, never by adding degrees to
the right ascension. That is the whole point: a constant step in RA shrinks as cos δ, so at
+80° declination a naive grid would place its tiles six times too close and cover a sixth of
the intended field. Near the pole, "a step in RA" stops meaning anything at all.

The step is `field × (1 − overlap)`, and the grid is centred on the target, so the mosaic is
symmetric around it.

The map draws each tile's **projected footprint** — a quadrilateral, not a rectangle. Far
from the centre a tile is genuinely distorted by the projection, and drawing it square would
promise a coverage you do not have.

## Parameters

- **`target`** — *str*. An object name resolved through Sesame (`M31`), or `ra,dec` in
  degrees. `set_center(ra, dec)` from the console skips the network entirely.
- **`reference_frame`** — *path*. A FITS file whose header carries `XPIXSZ`, `FOCALLEN`,
  `NAXIS1` and `NAXIS2`: the field is derived from them. Simply take one frame with the
  setup you plan to use.
- **`fov_width`**, **`fov_height`** — *real*, degrees. Explicit field; takes priority.
- **`tiles_x`**, **`tiles_y`** — *int*, the grid.
- **`overlap`** — *real*, percent, default `20`.
- **`size`** — *int*, size of the map in pixels.
- **`output_path`** — *path*. CSV `name,ra_deg,dec_deg`, which every planetarium and
  sequencer can import.
- **`new_image_id`** — *str*.

## Console

```python
planner = MosaicPlanner(target="M31", reference_frame="/data/one_light.fits",
                        tiles_x=3, tiles_y=2, overlap=25.0,
                        output_path="/data/m31_panels.csv")
app.run(planner)
for panel in planner.result["panels"]:
    print(panel["panel"], panel["ra"], panel["dec"])
```

## Tips & pitfalls

> **Warning** — 20 % of overlap is a floor, not a luxury. Registration needs stars **common**
> to two panels, and the edges of a field are exactly where optical aberrations and vignetting
> are worst. Below 15 %, the assembly seam becomes visible.

- The overlap is applied on both axes: 3×2 tiles at 20 % cover roughly `2.6 × 1.8` fields,
  not `3 × 2`.
- The map is a window like any other: put it beside a survey reference
  ([SurveyReference](retina-doc://SurveyReference)) with linked views to see what falls
  where.
- Once the frames are acquired, everything downstream is automatic: the pipeline's framing
  mode detects the panels, integrates each one and assembles them with
  [MosaicReproject](retina-doc://MosaicReproject).

## See also

- [MosaicReproject](retina-doc://MosaicReproject) — assemble the panels once acquired.
- [FindingChart](retina-doc://FindingChart) — the same synthetic TAN chart machinery.
- [PlateSolve](retina-doc://PlateSolve) — solve each panel, which the assembly requires.
- [SurveyReference](retina-doc://SurveyReference) — see the real sky over the planned field.

## References

- Calabretta, M. R. & Greisen, E. W. (2002) — *Representations of celestial coordinates in
  FITS*, A&A 395, 1077.
