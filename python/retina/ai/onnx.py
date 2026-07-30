"""Running an ONNX model over an image, by feathered tiles.

This code lived in ``StarRemoval``, as instance methods reading ``self.model`` and
``self.tile_size``. Yet there was nothing specific to star removal about it: network denoising
or deconvolution tile and feather in exactly the same way. Taking it out of a class was
therefore the condition for ``AIDenoise`` and ``AIDeconvolution`` to exist without copying
three screens of code.

Two gaps were filled along the way:

- **progress**. A 6000×4000 frame in 256-pixel tiles makes nearly four hundred inferences; they
  were mute and nothing could interrupt them. ``run_tiled`` now reports after each tile, and it
  is that report which carries the cancellation point.
- **the session cache**. ``InferenceSession`` was rebuilt on every execution, which on a small
  image costs more than the inference. It is memoized by path and modification time —
  replacing the model file is enough to change it.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import numpy as np

from ..i18n import translate as _t

#: open sessions, keyed by (path, mtime, providers). The mtime is part of it so that a model
#: rewritten in place is re-read rather than served again from memory.
_SESSIONS: dict[tuple, object] = {}


def feather(size: int, overlap: int) -> np.ndarray:
    """2D window with a linear ramp over ``overlap`` px at the edges (tile feathering)."""
    r = np.ones(size, dtype=np.float32)
    if overlap > 0:
        ramp = np.linspace(0.0, 1.0, overlap + 2, dtype=np.float32)[1:-1]
        r[: len(ramp)] = ramp
        r[-len(ramp):] = ramp[::-1]
    return np.outer(r, r)


def open_session(path: str, providers: list[str] | None = None):
    """Open (or serve again) an onnxruntime session for this model.

    ``providers`` defaults to CPU only. This is the GPU extension point — the day
    ``CUDAExecutionProvider`` is wired in, no caller changes.
    """
    import onnxruntime as ort

    if not path:
        raise ValueError(_t("open_session: empty model path"))
    if not os.path.exists(path):
        raise FileNotFoundError(_t("ONNX model not found: {path}").format(path=path))
    choisis = tuple(providers or ("CPUExecutionProvider",))
    key = (os.path.abspath(path), os.path.getmtime(path), choisis)
    session = _SESSIONS.get(key)
    if session is None:
        session = ort.InferenceSession(path, providers=list(choisis))
        _SESSIONS[key] = session
    return session


def forget_sessions() -> None:
    """Empty the session cache (tests, and future GPU memory release)."""
    _SESSIONS.clear()


def _layout(session) -> tuple[str, str]:
    """Name and layout of the input: ``NCHW`` if the second dimension is 3."""
    model_input = session.get_inputs()[0]
    shape = model_input.shape
    return model_input.name, ("NCHW" if (len(shape) == 4 and shape[1] == 3) else "NHWC")


def _positions(n: int, tile: int, pas: int) -> list[int]:
    """Tile origins along one axis; the last one is shifted so as to end at the edge."""
    if n <= tile:
        return [0]
    pos = list(range(0, n - tile + 1, pas))
    if pos[-1] != n - tile:
        pos.append(n - tile)
    return pos


def _infer(session, name: str, disposition: str, tile: np.ndarray,
           extra: dict[str, np.ndarray] | None) -> np.ndarray:
    t = tile.astype(np.float32)
    x = t.transpose(2, 0, 1)[None] if disposition == "NCHW" else t[None]
    entries = {name: x}
    if extra:
        entries.update(extra)
    output = np.squeeze(np.asarray(session.run(None, entries)[0]), axis=0)
    if output.ndim == 3 and output.shape[0] == 3:  # CHW → HWC
        output = output.transpose(1, 2, 0)
    return output


def run_tiled(data: np.ndarray, session, *, tile_size: int = 256, overlap: int = 32,
              extra_inputs: dict[str, np.ndarray] | None = None,
              progress: Callable[[float, int, int], None] | None = None) -> np.ndarray:
    """Apply the model over the whole image, by overlapping feathered tiles.

    ``data`` is an ``(H, W, C)`` float32 array. A single plane is **replicated** into three
    channels on input and re-averaged on output (these models are trained on RGB); beyond three
    channels, only the first three go through — alpha has no business in a denoising network.

    ``progress`` is called after each tile with ``(fraction, done, total)``. It is up to the
    caller to make it a progress report, a cancellation point, or both.
    """
    if data.ndim != 3:
        raise ValueError(_t("run_tiled expects an (H, W, C) array"))
    name, disposition = _layout(session)

    gray = data.shape[2] == 1
    src = np.repeat(data, 3, axis=2) if gray else data[:, :, :3]
    h, w, _ = src.shape
    ts = max(int(tile_size), 1)
    ov = max(int(overlap), 0)
    pas = max(ts - ov, 1)
    window = feather(ts, ov)

    origins_y = _positions(h, ts, pas)
    origins_x = _positions(w, ts, pas)
    total = len(origins_y) * len(origins_x)

    acc = np.zeros((h, w, 3), dtype=np.float32)
    weights = np.zeros((h, w), dtype=np.float32)
    done = 0
    for y in origins_y:
        for x in origins_x:
            th, tw = min(ts, h - y), min(ts, w - x)
            tile = src[y:y + th, x:x + tw, :]
            if th < ts or tw < ts:
                tile = np.pad(tile, ((0, ts - th), (0, ts - tw), (0, 0)), mode="reflect")
            output = _infer(session, name, disposition, tile, extra_inputs)
            m = window[:th, :tw]
            acc[y:y + th, x:x + tw, :] += output[:th, :tw, :] * m[:, :, None]
            weights[y:y + th, x:x + tw] += m
            done += 1
            if progress is not None:
                progress(done / total, done, total)

    res = acc / np.maximum(weights[:, :, None], 1e-6)
    if gray:
        res = res.mean(axis=2, keepdims=True)
    return res.astype(np.float32)
