"""Transporting pixels to the frontend.

A measurement spike settled two things this module applies:

**float16.** A float32 → float16 round trip introduces at most **0.043 LSB** of deviation
after STF — 23× below the visibility threshold, on very dark linear data where intuition says
the opposite (float16 is *floating*: its precision is relative, and a sky background at ~1e-3
stays far above the subnormals). We therefore halve the transport for free, and half-float
textures are filterable in base WebGL2 where float32 requires
``OES_texture_float_linear``.

**No STF LUT.** The STF is evaluated analytically in the shader (``mtf()`` is a closed form):
it therefore travels in the JSON snapshot, as three numbers per channel. Nothing binary.

The URL carries the generation (``?gen=N``): within one process, every pixel state has its
own URL, and invalidation is done by changing address. A stale generation answers **409**
rather than obsolete content — the client then waits for the next snapshot, which will give
it the right one.

**But that URL identifies the content only for a given run**, and that is what :data:`RUN_ID`
is for. View identifiers (``Image01``…) *and* generations both restart from 1 at every
startup: ``/api/pixels/Image01.f16?gen=1`` therefore designates a different image in every
session. Serving that address as ``immutable`` was a lie, and the WebView2 disk cache — which
survives restarts, in ``%LOCALAPPDATA%\\Retina`` — replayed the previous session's pixels.
Observed symptom: ``texImage2D`` fails ("ArrayBufferView not big enough") because the buffer
has the dimensions of the earlier image, and **the viewport stays black**. Worse, at equal
dimensions the upload succeeds and the screen silently shows another image's pixels.

We therefore revalidate systematically (``no-cache``) against an ``ETag`` prefixed by
:data:`RUN_ID`. The body is not retransmitted when nothing has moved (304), so the loop stays
as frugal as before over a loopback round trip, but a cache inherited from another run can no
longer be validated. The real time saving is elsewhere anyway: the frontend's texture cache
(``view:generation``) avoids the re-fetch within the current session.

**Lazy pyramid (tiling).** ``?scale=S`` (a power of 2) serves the reduced level S of the
view, ``?rect=X,Y,W,H`` (coordinates *of that level*) cuts a tile out of it. With no
parameter, the historical behavior is unchanged to the byte. The level is built on demand by
**cascaded 2×2 block averaging** — not ``execute_preview``'s stride, which is a speed choice
for a preview, not anti-aliasing for the reference display — and always from the domain's
float32, so as not to accumulate float16 rounding octave after octave. The LRU cache stores
the **whole level**; a tile is only a contiguous slice of that level. A level's dimensions
are ``ceil(dim / S)`` (the per-octave cascade of ``ceil`` is identical there), a formula the
client shares (``web/src/viewport/tiles.ts``).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections import OrderedDict
from concurrent.futures import Executor
from typing import TYPE_CHECKING

import numpy as np
from aiohttp import web

if TYPE_CHECKING:
    from ..app import Application
    from .state import SnapshotBuilder

log = logging.getLogger("retina.server")

#: Identifier of the **current process**, the prefix of every pixel ETag.
#:
#: It is what prevents a disk cache inherited from a previous session from being validated by
#: this one: ``view:Image01:1`` designates different pixels from one run to the next, but
#: ``<run>:view:Image01:1`` does not. Drawn once at import time, hence shared by every server
#: instance of one process — which is exactly the granularity wanted.
RUN_ID = secrets.token_hex(8)

#: Size of the write chunks. Without slicing, serving 144 MB would block the loop for the
#: duration of a single giant socket write.
CHUNK = 4 << 20

#: Cache ceilings. A 6000×4000×3 view weighs 144 MB in float16: without a bound, opening a
#: few images would blow up the server's memory. Raised along with tiling: level 1 of a 20k
#: image weighs ~450 MB, and the domain already carries several GB of float32 for such an
#: image — the cache stays in proportion.
MAX_ENTRIES = 16
MAX_BYTES = 1024 << 20

#: Guard on the ``scale`` parameter: 2^8 = 256 covers the gigapixel (100k px → 391 px).
MAX_SCALE = 256


class PixelService:
    """LRU cache of float16 buffers + the HTTP endpoints that serve them."""

    def __init__(
        self,
        app: Application,
        snapshots: SnapshotBuilder,
        executor: Executor,
    ) -> None:
        self._app = app
        self._snapshots = snapshots
        self._executor = executor
        self._cache: OrderedDict[tuple[str, int, int], np.ndarray] = OrderedDict()
        self._bytes = 0
        #: levels currently being built — N simultaneous tiles of the same level must
        #: compute it only once (computing level 1 of a 20k image takes seconds; without
        #: this lock, every tile would restart it).
        self._pending: dict[tuple[str, int, int], asyncio.Task] = {}

    # --- cache ----------------------------------------------------------------
    def _get_cached(self, key: tuple[str, int, int]) -> np.ndarray | None:
        buffer = self._cache.get(key)
        if buffer is not None:
            self._cache.move_to_end(key)
        return buffer

    def _put(self, key: tuple[str, int, int], buffer: np.ndarray) -> None:
        self._cache[key] = buffer
        self._bytes += buffer.nbytes
        while self._cache and (len(self._cache) > MAX_ENTRIES or self._bytes > MAX_BYTES):
            _, evicted = self._cache.popitem(last=False)
            self._bytes -= evicted.nbytes

    def drop(self, prefix: str) -> None:
        """Forget a view's buffers (window closing)."""
        for key in [k for k in self._cache if k[0] == prefix]:
            self._bytes -= self._cache.pop(key).nbytes

    @property
    def cached_bytes(self) -> int:
        return self._bytes

    # --- conversion -----------------------------------------------------------
    async def _as_f16(
        self, key: tuple[str, int, int], data: np.ndarray, scale: int = 1
    ) -> np.ndarray:
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        loop = asyncio.get_running_loop()
        task = self._pending.get(key)
        if task is None:
            # ~0.3 s for 288 MB: far too long for the loop, which must stay free to serve
            # progress and echoes during that time.
            task = loop.create_task(self._build(key, data, scale))
            self._pending[key] = task
            task.add_done_callback(lambda _t: self._pending.pop(key, None))
        # shield: a client disconnecting in the middle of the wait must not cancel the
        # build that other tiles are waiting on.
        return await asyncio.shield(task)

    async def _build(self, key: tuple[str, int, int], data: np.ndarray, scale: int) -> np.ndarray:
        loop = asyncio.get_running_loop()
        buffer = await loop.run_in_executor(self._executor, _to_f16_level, data, scale)
        self._put(key, buffer)
        return buffer

    # --- endpoints ------------------------------------------------------------
    async def handle_view(self, request: web.Request) -> web.StreamResponse:
        view_id = request.match_info["view_id"]
        try:
            view = self._app.view(view_id)
        except KeyError:
            raise web.HTTPNotFound(text=f"unknown view: {view_id}") from None
        current = self._snapshots.pixel_gen(view_id)
        gen = _requested_gen(request, current)
        scale = _requested_scale(request)
        rect = _requested_rect(request)
        return await self._serve(request, f"view:{view_id}", gen, view.image.data, scale, rect)

    async def handle_mask(self, request: web.Request) -> web.StreamResponse:
        window_id = request.match_info["window_id"]
        win = next((w for w in self._app.windows if w.id == window_id), None)
        if win is None or win.mask is None:
            raise web.HTTPNotFound(text=f"unknown mask: {window_id}")
        current = self._snapshots.mask_gen(window_id)
        gen = _requested_gen(request, current)
        scale = _requested_scale(request)
        rect = _requested_rect(request)
        return await self._serve(request, f"mask:{window_id}", gen, win.mask.data, scale, rect)

    async def _serve(
        self,
        request: web.Request,
        prefix: str,
        gen: int,
        data: np.ndarray,
        scale: int,
        rect: tuple[int, int, int, int] | None,
    ) -> web.StreamResponse:
        channels = 1 if data.ndim == 2 else int(data.shape[2])
        # What distinguishes these pixels from all the others of the same run: the view, its
        # generation, the pyramid level and the tile. Two requests of the same identity
        # return, by construction, the same content — that is what allows the 304.
        identity = f"{prefix}:{gen}:{scale}:{rect if rect is not None else 'full'}"
        if rect is not None and scale == 1:
            # Full-resolution tile: a slice of the domain's float32, converted on the fly —
            # never materialize (nor cache) the full-size float16 of a giant image.
            _validate_rect(rect, data.shape[1], data.shape[0])
            loop = asyncio.get_running_loop()
            buffer = await loop.run_in_executor(self._executor, _to_f16_rect, data, rect)
            return await stream_buffer(request, buffer, rect[2], rect[3], channels,
                                       scale=scale, identity=identity)
        buffer = await self._as_f16((prefix, gen, scale), data, scale)
        if rect is not None:
            _validate_rect(rect, buffer.shape[1], buffer.shape[0])
            x, y, w, h = rect
            tile = np.ascontiguousarray(buffer[y : y + h, x : x + w])
            return await stream_buffer(request, tile, w, h, channels,
                                       scale=scale, identity=identity)
        return await stream_buffer(
            request, buffer, buffer.shape[1], buffer.shape[0], channels,
            scale=scale if scale > 1 else None, identity=identity,
        )


def _to_f16(data: np.ndarray) -> np.ndarray:
    array = np.asarray(data, dtype=np.float32)
    if array.ndim == 2:
        array = array[:, :, np.newaxis]
    return np.ascontiguousarray(array.astype(np.float16))


def _halve(array: np.ndarray) -> np.ndarray:
    """One octave of reduction: 2×2 block averaging, edge replicated if a dimension is odd."""
    h, w, _c = array.shape
    if h % 2 or w % 2:
        array = np.pad(array, ((0, h % 2), (0, w % 2), (0, 0)), mode="edge")
    h2, w2 = array.shape[0] // 2, array.shape[1] // 2
    return array.reshape(h2, 2, w2, 2, -1).mean(axis=(1, 3), dtype=np.float32)


def _to_f16_level(data: np.ndarray, scale: int) -> np.ndarray:
    """Reduced level ``scale`` in float16 — the whole cascade costs ~4/3 of the first octave."""
    if scale <= 1:
        return _to_f16(data)
    array = np.asarray(data, dtype=np.float32)
    if array.ndim == 2:
        array = array[:, :, np.newaxis]
    while scale > 1:
        array = _halve(array)
        scale //= 2
    return np.ascontiguousarray(array.astype(np.float16))


def _to_f16_rect(data: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = rect
    sub = np.asarray(data[y : y + h, x : x + w], dtype=np.float32)
    if sub.ndim == 2:
        sub = sub[:, :, np.newaxis]
    return np.ascontiguousarray(sub.astype(np.float16))


def _requested_scale(request: web.Request) -> int:
    raw = request.query.get("scale")
    if raw is None:
        return 1
    try:
        scale = int(raw)
    except ValueError:
        raise web.HTTPBadRequest(text=f"invalid scale: {raw!r}") from None
    # a power of two: the pyramid is binary, any other step would make the level dimensions
    # unpredictable for the client
    if scale < 1 or scale > MAX_SCALE or scale & (scale - 1):
        raise web.HTTPBadRequest(text=f"invalid scale: {raw!r} (power of 2 ≤ {MAX_SCALE})")
    return scale


def _requested_rect(request: web.Request) -> tuple[int, int, int, int] | None:
    raw = request.query.get("rect")
    if raw is None:
        return None
    try:
        x, y, w, h = (int(part) for part in raw.split(","))
    except ValueError:
        raise web.HTTPBadRequest(text=f"invalid rect: {raw!r}") from None
    if x < 0 or y < 0 or w < 1 or h < 1:
        raise web.HTTPBadRequest(text=f"invalid rect: {raw!r}")
    return (x, y, w, h)


def _validate_rect(rect: tuple[int, int, int, int], width: int, height: int) -> None:
    x, y, w, h = rect
    if x + w > width or y + h > height:
        raise web.HTTPBadRequest(
            text=f"rect out of bounds: {rect} in {width}×{height}"
        )


def _requested_gen(request: web.Request, current: int | None) -> int:
    """Validate the ``?gen=`` against the published generation.

    A mismatch is not a client error: it is a normal race between its snapshot and a
    concurrent mutation. The 409 tells it "your generation is stale, wait for the next
    snapshot" — far safer than serving it pixels that do not match the state it believes it
    is displaying.
    """
    if current is None:
        raise web.HTTPConflict(text="unknown generation — wait for a snapshot")
    raw = request.query.get("gen")
    if raw is None:
        return current
    try:
        wanted = int(raw)
    except ValueError:
        raise web.HTTPBadRequest(text=f"invalid gen: {raw!r}") from None
    if wanted != current:
        raise web.HTTPConflict(text=f"stale generation ({wanted} ≠ {current})")
    return current


async def stream_buffer(
    request: web.Request,
    buffer: np.ndarray,
    width: int,
    height: int,
    channels: int,
    scale: int | None = None,
    identity: str = "",
) -> web.StreamResponse:
    """Serve a float16 buffer in chunks. Shared with the real-time preview.

    ``identity`` describes *what* these pixels are (view, generation, level, tile). Prefixed
    by :data:`RUN_ID`, it becomes the ``ETag`` — see the module header: without the prefix, a
    previous session's disk cache would get validated and the viewport would display another
    image's pixels.
    """
    view = memoryview(buffer).cast("B")
    etag = f'"{RUN_ID}:{identity}:{width}x{height}x{channels}"'
    headers = {
        "Content-Type": "application/octet-stream",
        # `no-cache` = "keep it, but come back and ask me": the body is not retransmitted
        # (304) as long as nothing moves, and never served from another run.
        "Cache-Control": "private, no-cache",
        "ETag": etag,
        "X-Retina-Width": str(width),
        "X-Retina-Height": str(height),
        "X-Retina-Channels": str(channels),
        "X-Retina-Dtype": "float16",
    }
    if scale is not None:
        headers["X-Retina-Scale"] = str(scale)
    if request.headers.get("If-None-Match") == etag:
        # 304: the client keeps its body *and* the X-Retina-* headers of the original 200.
        return web.Response(status=304, headers=headers)
    response = web.StreamResponse(headers=headers)
    response.content_length = view.nbytes
    await response.prepare(request)
    for offset in range(0, view.nbytes, CHUNK):
        await response.write(view[offset : offset + CHUNK])
    await response.write_eof()
    return response
