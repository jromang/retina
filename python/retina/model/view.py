"""View — the addressable target of a process (main view or preview).

A view carries the image, the STF (non-destructive), and a linear history (undo/redo). Every
process brackets its edit with ``begin_process`` / ``end_process``, which pushes a history
entry.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..i18n import translate as _t
from .image import Image
from .stf import STF


class ReplayError(RuntimeError):
    """A history chain that cannot be replayed, and the reason why."""


def _float_mask(data, shape, inverted: bool):
    """Normalize a mask array the way ``ImageWindow.mask_array`` does.

    The logic is knowingly and minimally duplicated: ``mask_array`` reads *the window* (its
    current mask, its current inversion), whereas replay starts from an identifier recorded in
    the history entry. Routing one through the other would mean setting and then restoring the
    window's mask — an observable side effect, for a three-line computation.
    """
    m = np.asarray(data, dtype=np.float32)
    if m.ndim == 2:
        m = m[:, :, np.newaxis]
    if m.shape[0] != shape[0] or m.shape[1] != shape[1]:
        raise ReplayError(
            _t("Mask {mask_shape} != image {image_shape}: incompatible dimensions.").format(
                mask_shape=m.shape[:2], image_shape=shape[:2]))
    if m.shape[2] > 1:
        m = m.mean(axis=2, keepdims=True)
    m = np.clip(m, 0.0, 1.0)
    return (1.0 - m) if inverted else m


@dataclass
class HistoryEntry:
    """A state of the view, and **what produced it**.

    Carrying the process instance is what makes the history replayable — that has long been
    the case. What was missing, and was added later, is the **mask in force at execution
    time**: the process read it off the window, and replaying the entry later would have
    applied the *current* mask, hence a different result with nothing to say so. Both fields
    have defaults, so a project written before that change still reads back unchanged.
    """

    label: str
    image: Image
    process: object | None = None  # the process instance that produced this state
    mask_id: str | None = None     # id of the view serving as mask, at execution time
    mask_inverted: bool = False


class View:
    def __init__(self, image: Image, view_id: str = "", is_preview: bool = False, window=None):
        self._image = image
        self.id = view_id
        self._is_preview = is_preview
        self.window = window
        self._stf: STF | None = None
        self.stf_enabled: bool = True  # display stretch active (F12 toggle)
        # history: list of states; index points at the current one
        self._history: list[HistoryEntry] = [HistoryEntry("initial", image)]
        self._index = 0
        self._pending_label: str | None = None
        self._pending_process: object | None = None
        self._pending_mask: tuple[str | None, bool] | None = None
        # Typed properties attached to the view — the "view properties" receptacle. What
        # made it necessary: `DynamicPSF` measurements lived only in the `job.done`
        # notification, and a reconnection or a mere panel close lost them, even though they
        # had cost a star detection. The content is JSON-serializable (it travels inside the
        # `.retina` file).
        self._properties: dict[str, object] = {}
        # Write counter: the snapshot publishes only a **summary** of the properties
        # (hundreds of stars × N views on every `state.changed` would be prohibitive), and it
        # is this number that tells the client it must re-request the data.
        self._properties_rev = 0

    # --- image / stf ----------------------------------------------------------
    @property
    def image(self) -> Image:
        return self._image

    def set_image(self, image: Image) -> None:
        self._image = image

    @property
    def is_preview(self) -> bool:
        return self._is_preview

    @property
    def is_main_view(self) -> bool:
        return not self._is_preview

    @property
    def stf(self) -> STF | None:
        return self._stf

    @stf.setter
    def stf(self, value: STF | None) -> None:
        self._stf = value

    def compute_auto_stf(self) -> STF:
        """Compute and install an auto-stretch STF, then return it."""
        self._stf = self._image.compute_auto_stretch()
        return self._stf

    # --- properties -----------------------------------------------------------
    @property
    def properties(self) -> dict[str, object]:
        """Properties attached to the view. Read-only — go through ``set_property``."""
        return dict(self._properties)

    @property
    def properties_rev(self) -> int:
        """Number of the last write — what the snapshot publishes."""
        return self._properties_rev

    def get_property(self, key: str, default: object = None) -> object:
        return self._properties.get(key, default)

    def set_property(self, key: str, value: object) -> None:
        """Set a property. ``None`` removes it — an absent key and a null key would be two
        ways of saying the same thing."""
        if value is None:
            self._properties.pop(key, None)
        else:
            self._properties[key] = value
        self._properties_rev += 1

    def load_properties(self, data: dict) -> None:
        """Restore properties from a project, without incrementing the write counter."""
        self._properties = dict(data or {})

    # --- process bracket / history --------------------------------------------
    def begin_process(self, label: str = "", process: object | None = None) -> None:
        self._pending_label = label
        self._pending_process = process
        self._pending_mask = None

    def note_mask(self, mask_id: str | None, inverted: bool = False) -> None:
        """Record the mask actually applied, for the entry in progress.

        Called by ``Process.execute_on`` **at the moment it reads the mask**, and not before:
        that is the only instant at which what really served is known.
        """
        self._pending_mask = (mask_id, bool(inverted))

    def abort_process(self) -> None:
        """Cancel a ``begin_process`` bracket without pushing an entry (process aborted):
        history and image stay intact."""
        self._pending_label = None
        self._pending_process = None
        self._pending_mask = None

    def end_process(self) -> None:
        label = self._pending_label or "process"
        process = self._pending_process
        mask = self._pending_mask or (None, False)
        self._pending_label = None
        self._pending_process = None
        self._pending_mask = None
        # truncate the redo branch, push the new current state
        del self._history[self._index + 1 :]
        self._history.append(
            HistoryEntry(label, self._image, process, mask[0], mask[1]))
        self._index += 1

    @property
    def history_index(self) -> int:
        return self._index

    @property
    def can_go_backward(self) -> bool:
        return self._index > 0

    @property
    def can_go_forward(self) -> bool:
        return self._index < len(self._history) - 1

    def undo(self) -> bool:
        if not self.can_go_backward:
            return False
        self._index -= 1
        self._image = self._history[self._index].image
        return True

    def redo(self) -> bool:
        if not self.can_go_forward:
            return False
        self._index += 1
        self._image = self._history[self._index].image
        return True

    def history_labels(self) -> list[str]:
        return [e.label for e in self._history]

    def go_to(self, index: int) -> bool:
        """Jump to an arbitrary history state (a click in the History panel)."""
        if not (0 <= index < len(self._history)):
            return False
        self._index = index
        self._image = self._history[index].image
        return True

    def history_entries(self) -> list[HistoryEntry]:
        """A copy of the list of states — the read counterpart of :meth:`restore_history`.

        A shallow copy: the entries themselves are shared, which is intended (their images are
        exactly what we want to serialize without duplicating), but reordering the returned
        list does not touch the history.
        """
        return list(self._history)

    def restore_history(self, entries: list[HistoryEntry], index: int) -> None:
        """Reinstall a complete history and its cursor — the entry point for loading.

        It exists so the project loader need not write ``_history``/``_index``: two private
        attributes set from the outside is an invariant that breaks at the first refactor. The
        invariant in question lives here, and is checked: non-empty history, index within
        bounds, and the current image **is** the one of the pointed-to entry — not a copy,
        without which ``undo()`` would jump to an array nobody displays.
        """
        if not entries:
            raise ValueError(_t("A history contains at least the initial state."))
        if not (0 <= index < len(entries)):
            raise ValueError(
                _t("History index out of range: {index} / {count}").format(
                    index=index, count=len(entries)
                )
            )
        self._history = list(entries)
        self._index = int(index)
        self._image = self._history[self._index].image
        self._pending_label = None
        self._pending_process = None
        self._pending_mask = None

    def replay(self, index: int, values: dict | None = None) -> bool:
        """Replay the chain from entry ``index``, with its parameters modified.

        **The non-destructive prototype.** Changing a setting made three steps earlier does
        not require redoing everything by hand: the history already carries each process
        instance, so it is enough to rebuild it with other values and replay everything
        downstream from the state that precedes it.

        Three choices make the prototype:

        - **Check first, execute second.** The whole chain is validated before a single pixel
          moves: one non-replayable entry (unknown process, vanished mask) fails the lot,
          history intact. A half-done replay would leave a view in a state nobody could
          describe.
        - **No branching.** The downstream is *replaced*, the old states go to the garbage
          collector. A graph-shaped history is precisely what we refuse to build before
          having a verdict — and the memory peak stays one state deep.
        - **The mask replayed is the entry's**, not the window's today. That is what
          ``mask_id`` is there to know.

        ``index`` is at least 1: entry 0 is the initial state, which no process produced.
        Returns ``True``; raises :class:`ReplayError` if the chain is not replayable.

        **Measured cost** (20 Mpx mono, 78 MB per state, an eight-step chain): replaying from
        the first step takes 0.71 s where building the chain takes 0.76 — no overhead of its
        own, the time is simply that of recomputing the downstream, and it decreases with
        depth (0.39 s from the fifth, 0.03 s from the last). The memory peak, on the other
        hand, rises by **+600 MB**, a transient doubling of the downstream: that is the price
        of atomicity, since the old states stay referenced until the new ones are all
        computed. Writing as we go would free them, but a process that raised midway would
        then leave a half-replayed history — the wrong trade.

        >>> view.replay(1, {"sigma": 3.5})   # step 1's convolution, set differently
        """
        if not (1 <= index < len(self._history)):
            raise ReplayError(
                _t("Nothing to replay at history index {index}.").format(index=index))

        downstream = self._history[index:]
        for position, entry in enumerate(downstream, start=index):
            self._check_replayable(entry, position)

        current = self._history[index - 1].image
        new_items: list[HistoryEntry] = []
        for position, entry in enumerate(downstream, start=index):
            process = entry.process
            if position == index and values:
                # Rebuild the instance rather than mutate the previous one: the constructor
                # revalidates and converts types, and the original entry stays intact if the
                # new value is refused.
                process = type(process)(**{**process.values(), **values})
            current = self._apply_to(process, current, entry)
            new_items.append(HistoryEntry(entry.label, current, process,
                                          entry.mask_id, entry.mask_inverted))

        self._history[index:] = new_items
        self._image = self._history[self._index].image
        return True

    def _check_replayable(self, entry: HistoryEntry, position: int) -> None:
        process = entry.process
        if process is None or not hasattr(process, "values"):
            raise ReplayError(
                _t("History step {index} ({label!r}) carries no replayable process.").format(
                    index=position, label=entry.label))
        if type(process).__name__ == "UnknownProcess":
            raise ReplayError(
                _t("History step {index} ({label!r}) comes from a process this "
                   "installation does not have.").format(index=position, label=entry.label))
        if entry.mask_id is not None and self._mask(entry.mask_id) is None:
            raise ReplayError(
                _t("History step {index} used mask {mask!r}, which no longer exists.").format(
                    index=position, mask=entry.mask_id))

    def _mask(self, mask_id: str):
        """Find the mask view by its id — ``None`` if it has vanished."""
        from ..process import context

        return context.resolve_image_full(mask_id)

    def _apply_to(self, process, image: Image, entry: HistoryEntry) -> Image:
        """One replayed step: the process, then the **recorded** mask."""
        original = image.data
        processed = process._apply(original)
        if entry.mask_id is not None and getattr(process, "is_maskable", True):
            mask = self._mask(entry.mask_id)
            if mask is not None and processed.shape == original.shape:
                m = _float_mask(mask, original.shape, entry.mask_inverted)
                processed = (original * (1.0 - m) + processed * m).astype(processed.dtype)
        return image.with_data(processed)

    def history_processes(self) -> list[object]:
        """The process instances applied up to the current state (initial excluded)."""
        return [e.process for e in self._history[1 : self._index + 1] if e.process is not None]

    def recipe(self):
        """Build a replayable :class:`ProcessContainer` from the history.

        This is the reproducibility feature: the exact same sequence of processes is replayed
        on another view or image.
        """
        from ..process.container import ProcessContainer

        return ProcessContainer(self.history_processes())

    def __repr__(self) -> str:
        kind = "preview" if self._is_preview else "main"
        return f"View(id={self.id!r}, {kind}, {self._image!r})"
