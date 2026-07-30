"""Real-time preview.

Adjusting a parameter must show its effect right away, without applying anything to the view.
Three mechanisms make that sustainable:

**Decimation.** ``Process.execute_preview`` reduces the image to 1024 px on its long side
before computing: a deconvolution on a 6000×4000 exposure would take seconds, on the preview
it takes a few tens of milliseconds.

**Generation counter.** Every request increments a counter; a result whose generation is no
longer the current one is dropped. Without that, a slow computation started before a fast one
would overwrite the recent result — the preview would flicker back to a stale state.

**One preview per form.** Every owner has its own slot: comparing the effect of two processes
requires seeing both, and the old single-owner rule silently evicted the first as soon as the
second was checked. The number of slots is bounded — each holds a decimated image, and a form
left open must not keep one forever. The debounce stays client-side: it is the client that
knows when the user has finished moving a slider.

Generations are still drawn from a **global counter**, and not from a per-owner counter: it is
the identifier `/api/rtp.f16?gen=N` carries, and two slots numbering on their own would end up
serving one another's pixels.

**The preview carries the view it represents** (``info["view"]``): the client panel renders
the before/after curtain and the STF from *that* view, not from the active view — the two
diverge as soon as the user changes view during a computation. Following the active view
("Track View") is a presentation behavior, entirely client-side: the form asks for a new
preview when the active view changes, the server retains nothing. No ``app.*`` equivalent to
look for here — RTP is shell plumbing, non-mutating and echo-free, like ``layout.*``; console
parity lives at the right level, ``Process.execute_preview(image)``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Executor
from typing import TYPE_CHECKING, Any

import numpy as np

from ..process import context
from ..process.progress import ProcessCancelled, ProgressMonitor
from .rpc import DOMAIN_ERROR, RpcError

if TYPE_CHECKING:
    from ..app import Application

log = logging.getLogger("retina.server")

RTP_METHODS: dict[str, bool] = {
    "rtp.request": False,
    "rtp.release": False,
}

#: Longest side of the preview: beyond that, the compute cost outweighs the point of a preview.
MAX_SIZE = 1024

#: Previews kept alive simultaneously. Comparing two settings calls for two; beyond that, we
#: mostly keep decimated images of forms one has stopped looking at.
MAX_PREVIEWS = 4


class _Slot:
    """An owner's preview: its last image and the computation in flight."""

    __slots__ = ("buffer", "generation", "info", "monitor", "view_id")

    def __init__(self) -> None:
        self.generation = 0
        self.monitor: ProgressMonitor | None = None
        self.buffer: np.ndarray | None = None
        self.info: dict = {}
        #: canonical view id of the last preview requested — the owner keeps its slot when
        #: it changes view, only the published frame's `view` changes.
        self.view_id: str | None = None


class RtpService:
    """One preview per form; from a form, the last one computed and nothing else."""

    def __init__(
        self,
        app: Application,
        executor: Executor,
        notify: Callable[[str, dict], None],
    ) -> None:
        self._app = app
        self._executor = executor
        self._notify = notify
        self._generation = 0
        #: slots by owner, from the oldest to the most recently solicited
        self._slots: dict[str, _Slot] = {}

    @staticmethod
    def _key(owner: str | None) -> str:
        """An anonymous owner is still an owner — the same one for everybody."""
        return owner or ""

    def owners(self) -> list[str]:
        return list(self._slots)

    # --- control --------------------------------------------------------------
    def request(
        self, process_id: str, params: dict | None, view: str, owner: str | None = None
    ) -> int:
        """Schedule a preview and return its generation."""
        from ..process.registry import get

        cls = get(process_id)
        if cls.is_global or getattr(cls, "creates_window", False):
            raise RpcError(
                DOMAIN_ERROR, f"{process_id}: no preview (global process)"
            )
        try:
            instance = cls(**(params or {}))
        except TypeError as exc:
            raise RpcError(DOMAIN_ERROR, f"{process_id}: invalid parameter — {exc}") from None

        try:
            target = self._app.view(view)
        except KeyError:
            raise RpcError(DOMAIN_ERROR, f"unknown view: {view!r}") from None

        key = self._key(owner)
        slot = self._slots.pop(key, None) or _Slot()
        self._slots[key] = slot  # reinserted at the end: it is the most recently solicited
        self._evict()

        # Cancels **this** owner's computation in flight: its result would be dropped
        # anyway. The other slots are not affected — that is the whole point of splitting
        # by owner.
        if slot.monitor is not None:
            slot.monitor.cancel()

        self._generation += 1
        slot.generation = self._generation
        slot.view_id = target.id
        monitor = ProgressMonitor()
        slot.monitor = monitor
        # The view id travels as a parameter: it is the immutable snapshot of this
        # generation, even if the owner asks again meanwhile on another view.
        self._executor.submit(
            self._run, key, slot.generation, instance, target.image, monitor, target.id
        )
        return slot.generation

    def _evict(self) -> None:
        """Close the oldest slots beyond the limit."""
        while len(self._slots) > MAX_PREVIEWS:
            previous = next(iter(self._slots))
            self.release(previous)
            self._notify("rtp.released", {"owner": previous})

    def release(self, owner: str | None = None) -> None:
        """A form hands back control. With no owner, every preview is released."""
        keys = [self._key(owner)] if owner is not None else list(self._slots)
        for key in keys:
            slot = self._slots.pop(key, None)
            if slot is not None and slot.monitor is not None:
                slot.monitor.cancel()

    # --- computation ----------------------------------------------------------
    def _run(
        self,
        owner: str,
        generation: int,
        process: Any,
        image: Any,
        monitor: ProgressMonitor,
        view_id: str,
    ) -> None:
        context.set_monitor(monitor)
        started = time.perf_counter()

        def stale() -> bool:
            """Has the owner handed back control, or asked again since?"""
            slot = self._slots.get(owner)
            return slot is None or slot.generation != generation

        try:
            result = process.execute_preview(image, max_size=MAX_SIZE)
            if stale():
                return  # a more recent request came through: this result is stale
            data = np.asarray(result.data, dtype=np.float32)
            if data.ndim == 2:
                data = data[:, :, np.newaxis]
            slot = self._slots[owner]
            slot.buffer = np.ascontiguousarray(data.astype(np.float16))
            slot.info = {
                "generation": generation,
                "owner": owner or None,
                "view": view_id,
                "width": int(data.shape[1]),
                "height": int(data.shape[0]),
                "channels": int(data.shape[2]),
                "seconds": round(time.perf_counter() - started, 4),
            }
            self._notify("rtp.ready", dict(slot.info))
        except ProcessCancelled:
            pass  # replaced by a more recent request: silence is intended
        except Exception as exc:
            if not stale():
                self._notify(
                    "rtp.failed",
                    {"generation": generation, "owner": owner or None, "view": view_id,
                     "message": f"{type(exc).__name__}: {exc}"},
                )
        finally:
            context.set_monitor(None)

    # --- HTTP service ---------------------------------------------------------
    def buffer_for(self, generation: int) -> tuple[np.ndarray, dict] | None:
        """Buffer of that generation, or ``None`` if it is stale.

        The generation is enough to designate the slot: the counter is global, so two live
        previews never bear the same number.
        """
        for slot in self._slots.values():
            if slot.buffer is not None and slot.info.get("generation") == generation:
                return slot.buffer, slot.info
        return None


class RtpHandlers:
    def __init__(self, service: RtpService) -> None:
        self._service = service

    def request(
        self, process_id: str, view: str, params: dict | None = None, owner: str | None = None
    ) -> dict:
        """Request a decimated preview. Debouncing is the client's responsibility."""
        return {"generation": self._service.request(process_id, params, view, owner)}

    def release(self, owner: str | None = None) -> None:
        """Release the preview (the owning form was closed or unchecked)."""
        self._service.release(owner)
