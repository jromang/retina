"""PNG rendering of a view — how an agent *sees* an image.

An agent that has only statistics works blind: it will see neither a background gradient, nor
a halo, nor stars elongated by a tracking fault. This tool returns a thumbnail exactly as the
viewport shows it.

# Two precautions that are not details

**Downsample before stretching.** A 6000×4000×3 frame in float32 weighs 274 MiB; applying the
STF to it only to keep a thousand pixels of width would allocate as much a second time. We
first reduce by block averaging, then stretch — the visual result is the same, the memory is
divided by the square of the factor.

**Block averaging, not dumb decimation.** Taking one pixel out of N on a starry sky makes the
stars vanish (they only span a few pixels): the agent would see an empty field and conclude
wrongly. Averaging keeps them as attenuated blobs.
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

import numpy as np

from .tools import ImageResult, ToolError

if TYPE_CHECKING:
    from ..core import ServerApp

STRETCH_MODES = ("auto", "current", "none")


async def render_png(
    server: ServerApp, view_id: str, *, max_size: int = 1024, stretch: str = "current"
) -> ImageResult:
    """Renders the view as an 8-bit PNG, on the server's thread pool."""
    if stretch not in STRETCH_MODES:
        raise ToolError(f"Unknown stretch: {stretch!r} ({', '.join(STRETCH_MODES)})")
    try:
        view = server.app.view(view_id)
    except KeyError:
        raise ToolError(f"Unknown view: {view_id!r}") from None

    image = view.image
    # The view's STF is read here, on the loop: the worker only touches arrays.
    stf = view.stf if stretch == "current" else None
    loop = asyncio.get_running_loop()
    png, width, height = await loop.run_in_executor(
        server.jobs, _encode, image, stf, stretch, int(max_size)
    )
    caption = (
        f"{view_id}: {image.width}×{image.height}×{image.channels}, "
        f"rendered at {width}×{height} with stretch={stretch}"
    )
    return ImageResult(png=png, caption=caption)


def _encode(image, stf, stretch: str, max_size: int) -> tuple[bytes, int, int]:
    from PIL import Image as PilImage

    data = _downsample(np.asarray(image.data, dtype=np.float32), max_size)
    if data.ndim == 2:
        data = data[:, :, np.newaxis]

    if stretch == "auto":
        # Recomputed on the thumbnail: the robust statistics of an image reduced by
        # averaging remain those of the sky background, which is what auto-stretch targets.
        from ...model.stf import STF

        stf = STF.auto_from_image(_Stats(data))
    if stf is not None:
        data = stf.apply(data)

    eight_bit = np.clip(data * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)
    if eight_bit.shape[2] == 1:
        pil = PilImage.fromarray(eight_bit[:, :, 0], mode="L")
    elif eight_bit.shape[2] >= 3:
        pil = PilImage.fromarray(eight_bit[:, :, :3], mode="RGB")
    else:  # two channels: nothing standard, we show the first one
        pil = PilImage.fromarray(eight_bit[:, :, 0], mode="L")

    buffer = io.BytesIO()
    pil.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), pil.width, pil.height


def _downsample(data: np.ndarray, max_size: int) -> np.ndarray:
    """Reduces by averaging whole blocks, without an external dependency."""
    height, width = data.shape[:2]
    factor = int(np.ceil(max(height, width) / max(max_size, 1)))
    if factor <= 1:
        return data
    # Crop to the lower multiple: a few lines lost at the edge are better than an uneven
    # resampling, which would distort the geometry announced in the caption.
    trimmed = data[: (height // factor) * factor, : (width // factor) * factor]
    if trimmed.ndim == 2:
        trimmed = trimmed[:, :, np.newaxis]
    blocks = trimmed.reshape(
        trimmed.shape[0] // factor, factor, trimmed.shape[1] // factor, factor, trimmed.shape[2]
    )
    return blocks.mean(axis=(1, 3), dtype=np.float32)


class _Stats:
    """Minimal adapter: ``STF.auto_from_image`` only needs these three methods.

    Building a real :class:`~retina.model.image.Image` would work too, but would bring a
    domain object — with its history and its hooks — into a rendering path that has only an
    array to describe.
    """

    def __init__(self, data: np.ndarray) -> None:
        self._data = data

    @property
    def channels(self) -> int:
        return self._data.shape[2]

    def median(self, channel: int) -> float:
        return float(np.median(self._data[:, :, channel]))

    def madn(self, channel: int) -> float:
        plane = self._data[:, :, channel]
        return float(np.median(np.abs(plane - np.median(plane))) * 1.4826)
