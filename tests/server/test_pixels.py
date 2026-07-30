"""Pixel transport: float16 conversion, addressing by generation, caching.

The delicate point is **invalidation**. The domain emits no signal when an image changes; the
server deduces it from the replacement of the numpy array (cf. ``state.py``). These tests check
that the deduction is right in the three cases that matter: applying a process, undo, and
jumping through the history.
"""

from __future__ import annotations

import numpy as np
from retina.processes.channels import Invert
from retina.server import pixels


async def _fetch(client, path: str, **headers: str):
    return await client.get(path, headers={"X-Retina-Token": client.retina.token, **headers})


async def test_f16_pixels_byte_for_byte(client, domain):
    """The served buffer must be exactly the float16 conversion of the domain's data."""
    gen = client.retina.snapshots.build()["windows"][0]["views"][0]["pixel_gen"]
    resp = await _fetch(client, f"/api/pixels/Test01.f16?gen={gen}")
    assert resp.status == 200

    body = await resp.read()
    expected = domain.view("Test01").image.data.astype(np.float16)
    assert body == expected.tobytes()
    assert len(body) == expected.nbytes
    assert resp.headers["X-Retina-Width"] == "24"
    assert resp.headers["X-Retina-Height"] == "16"
    assert resp.headers["X-Retina-Channels"] == "3"
    assert resp.headers["X-Retina-Dtype"] == "float16"


async def test_pixels_revalidate_instead_of_freezing(client):
    """``immutable`` was a lie: the address does not designate the same content from one run
    to the next (view ids *and* generations both restart at 1)."""
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/pixels/Test01.f16")
    assert resp.headers["Cache-Control"] == "private, no-cache"
    assert resp.headers["ETag"].startswith(f'"{pixels.RUN_ID}:')


async def test_the_same_run_spares_the_body(client):
    """Revalidation must not cost a transfer: nothing moved, so 304."""
    client.retina.snapshots.build()
    first = await _fetch(client, "/api/pixels/Test01.f16")
    etag = first.headers["ETag"]

    second = await _fetch(client, "/api/pixels/Test01.f16", **{"If-None-Match": etag})

    assert second.status == 304
    assert await second.read() == b""


async def test_a_cache_inherited_from_another_run_cannot_be_validated(client, domain):
    """The regression that made the viewport go black.

    WebView2 keeps its **disk** cache between two launches. Since
    ``/api/pixels/Image01.f16?gen=1`` designates a different image in every session, the
    browser replayed the previous one's pixels: ``texImage2D`` failed on dimensions that were
    no longer the right ones, and nothing was displayed at all.
    """
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/pixels/Test01.f16")
    # Same logical identity (view, generation, level), but drawn from another process.
    stale = resp.headers["ETag"].replace(pixels.RUN_ID, "0" * len(pixels.RUN_ID))

    replayed = await _fetch(client, "/api/pixels/Test01.f16", **{"If-None-Match": stale})

    assert replayed.status == 200, "an ETag from another run must never be validated"
    expected = domain.view("Test01").image.data.astype(np.float16)
    assert await replayed.read() == expected.tobytes()


async def test_a_stale_generation_answers_409(client):
    """Better to refuse than to serve pixels that do not match the announced state."""
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/pixels/Test01.f16?gen=999")
    assert resp.status == 409


async def test_an_unknown_view_answers_404(client):
    resp = await _fetch(client, "/api/pixels/Ghost.f16")
    assert resp.status == 404


async def test_an_unknown_generation_answers_409(client, domain):
    """Asking for the pixels of a never-published view: the client must wait for a snapshot."""
    domain.new_preview(1, 1, 5, 5, "Zone")
    resp = await _fetch(client, "/api/pixels/Zone.f16")
    assert resp.status == 409


async def test_the_generation_changes_after_a_process_is_applied(client, domain):
    """The nominal case: applying a process replaces the array, hence the generation."""
    before = client.retina.snapshots.build()["windows"][0]["views"][0]["pixel_gen"]
    Invert().execute_on(domain.active_view)
    after = client.retina.snapshots.build()["windows"][0]["views"][0]["pixel_gen"]
    assert after == before + 1


async def test_the_generation_changes_after_undo(client, domain):
    Invert().execute_on(domain.active_view)
    applied = client.retina.snapshots.build()["windows"][0]["views"][0]["pixel_gen"]
    domain.undo()
    undone = client.retina.snapshots.build()["windows"][0]["views"][0]["pixel_gen"]
    assert undone == applied + 1


async def test_the_generation_is_stable_without_a_change(client):
    """Rebuilding the snapshot must not invalidate the client's pixels for nothing."""
    snapshots = client.retina.snapshots
    first = snapshots.build()["windows"][0]["views"][0]["pixel_gen"]
    for _ in range(3):
        again = snapshots.build()["windows"][0]["views"][0]["pixel_gen"]
    assert again == first


async def test_pixels_after_a_process_match_the_new_state(client, domain):
    Invert().execute_on(domain.active_view)
    gen = client.retina.snapshots.build()["windows"][0]["views"][0]["pixel_gen"]
    resp = await _fetch(client, f"/api/pixels/Test01.f16?gen={gen}")
    body = await resp.read()
    assert body == domain.view("Test01").image.data.astype(np.float16).tobytes()


async def test_the_mask_is_served_and_versioned(client, domain):
    from retina.model.image import Image

    mask = Image(np.linspace(0, 1, 24 * 16, dtype=np.float32).reshape(16, 24, 1))
    domain.set_mask(mask)
    snapshot = client.retina.snapshots.build()
    assert snapshot["windows"][0]["mask"]["gen"] == 1

    resp = await _fetch(client, "/api/mask/Test01.f16?gen=1")
    assert resp.status == 200
    assert await resp.read() == mask.data.astype(np.float16).tobytes()


async def test_a_missing_mask_answers_404(client):
    resp = await _fetch(client, "/api/mask/Test01.f16")
    assert resp.status == 404


async def test_the_cache_reuses_the_buffer(client):
    """Two requests on the same generation must convert only once."""
    client.retina.snapshots.build()
    await _fetch(client, "/api/pixels/Test01.f16")
    first = client.retina.pixels.cached_bytes
    await _fetch(client, "/api/pixels/Test01.f16")
    assert client.retina.pixels.cached_bytes == first


async def test_a_monochrome_image_is_served_in_3d(client, domain):
    """An (H, W) image must come out as (H, W, 1) — the shader always expects 3 dimensions."""
    from retina.model.image import Image

    domain.new_window(Image(np.zeros((4, 6), dtype=np.float32)), window_id="Mono")
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/pixels/Mono.f16")
    assert resp.status == 200
    assert resp.headers["X-Retina-Channels"] == "1"
    assert len(await resp.read()) == 4 * 6 * 1 * 2


# --- pyramid and tiles --------------------------------------------------------
def _reference_halve(array: np.ndarray) -> np.ndarray:
    """Reference 2×2 mean, written differently from the implementation (edge pad + reshape)."""
    h, w, c = array.shape
    out = np.zeros(((h + 1) // 2, (w + 1) // 2, c), dtype=np.float32)
    for yy in range(out.shape[0]):
        for xx in range(out.shape[1]):
            ys = slice(yy * 2, min(yy * 2 + 2, h))
            xs = slice(xx * 2, min(xx * 2 + 2, w))
            block = array[ys, xs]
            # replicated edge: the mean of a truncated block weights as if the last
            # row/column were doubled
            pady = 2 - block.shape[0]
            padx = 2 - block.shape[1]
            block = np.pad(block, ((0, pady), (0, padx), (0, 0)), mode="edge")
            out[yy, xx] = block.mean(axis=(0, 1))
    return out


async def test_scale_2_dimensions_and_content(client, domain):
    """Level 2 is the mean over 2×2 blocks — not a strided decimation."""
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/pixels/Test01.f16?scale=2")
    assert resp.status == 200
    assert resp.headers["X-Retina-Width"] == "12"
    assert resp.headers["X-Retina-Height"] == "8"
    assert resp.headers["X-Retina-Scale"] == "2"

    data = domain.view("Test01").image.data.astype(np.float32)
    expected = _reference_halve(data).astype(np.float16)
    got = np.frombuffer(await resp.read(), dtype=np.float16).reshape(8, 12, 3)
    assert np.array_equal(got, expected)


async def test_scale_on_odd_dimensions(client, domain):
    """ceil at each octave: 7×5 reduced ×4 gives 2×2, edge replicated (no NaN, no crash)."""
    from retina.model.image import Image

    y, x = np.mgrid[0:5, 0:7].astype(np.float32)
    domain.new_window(Image(((x + y) / 12.0)[:, :, np.newaxis]), window_id="Odd")
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/pixels/Odd.f16?scale=4")
    assert resp.status == 200
    assert resp.headers["X-Retina-Width"] == "2"  # ceil(7/4)
    assert resp.headers["X-Retina-Height"] == "2"  # ceil(5/4)
    got = np.frombuffer(await resp.read(), dtype=np.float16)
    assert np.isfinite(got.astype(np.float32)).all()


async def test_a_full_resolution_rect_is_byte_exact(client, domain):
    """A scale=1 tile is the exact slice of the domain's float32."""
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/pixels/Test01.f16?rect=3,2,5,4")
    assert resp.status == 200
    assert resp.headers["X-Retina-Width"] == "5"
    assert resp.headers["X-Retina-Height"] == "4"
    expected = domain.view("Test01").image.data[2:6, 3:8].astype(np.float16)
    assert await resp.read() == np.ascontiguousarray(expected).tobytes()


async def test_a_rect_on_a_reduced_level(client, domain):
    """The rect is expressed in the level's coordinates: a tile of level 2."""
    client.retina.snapshots.build()
    level = await _fetch(client, "/api/pixels/Test01.f16?scale=2")
    full = np.frombuffer(await level.read(), dtype=np.float16).reshape(8, 12, 3)
    tile = await _fetch(client, "/api/pixels/Test01.f16?scale=2&rect=4,1,6,5")
    got = np.frombuffer(await tile.read(), dtype=np.float16).reshape(5, 6, 3)
    assert np.array_equal(got, full[1:6, 4:10])


async def test_an_invalid_scale_answers_400(client):
    client.retina.snapshots.build()
    for scale in ("3", "0", "-2", "abc", "512"):
        resp = await _fetch(client, f"/api/pixels/Test01.f16?scale={scale}")
        assert resp.status == 400, scale


async def test_an_invalid_rect_answers_400(client):
    client.retina.snapshots.build()
    for rect in ("1,2,3", "0,0,0,4", "-1,0,4,4", "20,0,10,4", "0,14,4,4"):
        resp = await _fetch(client, f"/api/pixels/Test01.f16?rect={rect}")
        assert resp.status == 400, rect


async def test_a_scale_with_a_stale_generation_answers_409(client):
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/pixels/Test01.f16?gen=999&scale=2")
    assert resp.status == 409


async def test_the_mask_with_a_scale(client, domain):
    from retina.model.image import Image

    mask = Image(np.random.default_rng(7).random((16, 24, 1)).astype(np.float32))
    domain.windows[0].set_mask(mask)
    client.retina.snapshots.build()
    resp = await _fetch(client, "/api/mask/Test01.f16?scale=2")
    assert resp.status == 200
    assert resp.headers["X-Retina-Width"] == "12"
    expected = _reference_halve(mask.data.astype(np.float32)).astype(np.float16)
    got = np.frombuffer(await resp.read(), dtype=np.float16).reshape(8, 12, 1)
    assert np.array_equal(got, expected)


async def test_a_level_is_built_only_once_under_concurrent_requests(client):
    """The anti-duplication lock: N simultaneous tiles, a single build of the level."""
    import asyncio as aio

    client.retina.snapshots.build()
    service = client.retina.pixels
    count = {"n": 0}
    original = service._build

    async def counter(key, data, scale):
        count["n"] += 1
        return await original(key, data, scale)

    service._build = counter
    try:
        responses = await aio.gather(
            *[_fetch(client, "/api/pixels/Test01.f16?scale=2&rect=0,0,4,4") for _ in range(6)]
        )
    finally:
        service._build = original
    assert all(r.status == 200 for r in responses)
    assert count["n"] == 1
