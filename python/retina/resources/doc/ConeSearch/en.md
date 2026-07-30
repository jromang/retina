---
id: ConeSearch
category: Global
title: Cone Search
brief: Lists the named objects of the field from SIMBAD, with their type and magnitude.
keywords: [SIMBAD, cone search, identification, object type, catalogue, annotation, variable star]
related: [GaiaCatalog, APASSCatalog, CatalogAnnotation, LightCurve, PlateSolve]
icon: list-details
references:
  - "Wenger, M. et al. (2000) — The SIMBAD astronomical database, A&AS 143, 9."
  - "CDS Strasbourg — SIMBAD (https://simbad.cds.unistra.fr)."
---

## Summary

`GaiaCatalog` and `APASSCatalog` return positions and magnitudes; they do not know that one
of those sources is called M51 and another is a variable star. `ConeSearch` adds exactly
that: a **name**, an **object type** and a magnitude, queried from SIMBAD for the field
covered by the view's astrometric solution.

Read-only: it measures, it does not touch pixels. Requires a WCS
([PlateSolve](retina-doc://PlateSolve), or a file that already carries one).

## Use cases

- Say **what you photographed** — the galaxies, nebulae and clusters that fell in the frame,
  by name.
- Find the **target of a light curve**: filter on `V*` and you get the variable stars of the
  field, with the coordinates to paste into
  [LightCurve](retina-doc://LightCurve).
- Prepare an annotation: feed the result to
  [CatalogAnnotation](retina-doc://CatalogAnnotation) to draw the identified objects.

## How it works

The centre of the view is converted to celestial coordinates, a cone of `radius` degrees is
queried from SIMBAD, and every returned object is projected back into pixels through the
same WCS. Objects that fall outside the frame are dropped — the cone is circular, the frame
is not.

`radius = 0` (the default) uses the **half-diagonal of the field**, capped at 5°: it is the
smallest cone that certainly covers the frame, and a much larger one would return thousands
of objects only to throw them away after projection.

## Parameters

- **`radius`** — *real*, degrees, default `0` (the field itself).
- **`max_objects`** — *int*, default `200`.
- **`object_types`** — *str*, comma-separated SIMBAD `otype` **prefixes**; empty keeps
  everything. Prefixes rather than exact values because SIMBAD's types are hierarchical:
  `G` catches `G`, `GiG`, `GiC`, `IG`…, and `V*` catches every kind of variable star.

## Result

`.result` holds `{n_objects, objects, columns}`, each object carrying `name`, `ra`, `dec`,
`otype`, `mag` (possibly `None` — SIMBAD does not have a V magnitude for everything) and its
pixel position `x`, `y`.

## Console

```python
search = ConeSearch(object_types="V*")
search.execute_on(app.active_view)
for obj in search.result["objects"]:
    print(obj["name"], obj["otype"], obj["ra"], obj["dec"])
```

## Tips & pitfalls

> **Note** — SIMBAD lists what has been **published**. An absence means no one has
> catalogued the object, not that there is nothing there. For a systematic star catalogue,
> use [GaiaCatalog](retina-doc://GaiaCatalog) instead.

- The query goes over the network and is not cached: on a wide field with a large
  `max_objects`, it takes a few seconds.
- `set_objects([...])` injects a list directly, which is how the tests run without touching
  the network — and how you can work offline from a saved catalogue.

## See also

- [GaiaCatalog](retina-doc://GaiaCatalog) — systematic star catalogue with precise
  photometry.
- [APASSCatalog](retina-doc://APASSCatalog) — V magnitudes, useful as comparison stars.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — draw a catalogue over the image.
- [LightCurve](retina-doc://LightCurve) — measure one of the variables you just found.

## References

- Wenger, M. et al. (2000) — *The SIMBAD astronomical database*, A&AS 143, 9.
- CDS Strasbourg — SIMBAD.
