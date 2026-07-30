"""Uniqueness of view identifiers — what all pixel addressing depends on.

Pixel transport addresses a view **globally**: the URL is `/api/pixels/<id>.f16` and the
generation is held under the key `view:<id>` (`server/state.py`). Two views with the same name
in two different windows therefore break three things at once:

- `app.view(id)` returns the first one found, so not necessarily the one being designated;
- the generation alternates between two arrays on every snapshot, so the client can never
  again request a valid generation — it gets 409s in a loop and the view never displays;
- `ProcessContainer.set_mask(i, view_id)` designates a mask by identifier, and would resolve
  the wrong one.

This was not theoretical: default identifiers were numbered **per window**, so opening two
images and creating a preview in each produced two `Preview01`.
"""

from __future__ import annotations

import numpy as np
from retina.model.image import Image


def _gen(snapshots, view_id: str) -> int | None:
    snapshots.build()
    return snapshots.pixel_gen(view_id)


async def test_default_previews_of_two_windows_do_not_collide(client, domain):
    domain.new_window(Image(np.full((20, 20, 1), 0.5, dtype=np.float32)), window_id="Second")

    first_window = next(w for w in domain.windows if w.id == "Test01")
    second = next(w for w in domain.windows if w.id == "Second")
    a = first_window.create_preview(1, 1, 9, 9)
    b = second.create_preview(2, 2, 8, 8)

    assert a.id != b.id, "two default previews used to carry the same identifier"
    # And each one is genuinely reachable by its identifier.
    assert domain.view(a.id) is a
    assert domain.view(b.id) is b


async def test_pixel_generation_stays_stable_with_two_previews(client, domain):
    """The visible symptom of the collision: a generation that never settles.

    Without uniqueness, the key `view:Preview01` received the pixels of one then the other in
    turn, and its counter incremented on every snapshot — the client always asked for a
    generation that had already expired.
    """
    domain.new_window(Image(np.full((20, 20, 1), 0.5, dtype=np.float32)), window_id="Second")
    first_window = next(w for w in domain.windows if w.id == "Test01")
    second = next(w for w in domain.windows if w.id == "Second")
    a = first_window.create_preview(1, 1, 9, 9)
    second.create_preview(2, 2, 8, 8)

    snapshots = client.retina.snapshots
    first = _gen(snapshots, a.id)
    for _ in range(3):
        last = _gen(snapshots, a.id)
    assert last == first, "the pixel generation must stay stable without a mutation"
