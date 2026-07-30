"""Camera RAW loading (rawpy/LibRaw).

RAW files (.cr2/.cr3/.nef/.arw/.dng/.raf…) contain a linear Bayer matrix. Two paths are
exposed: ``linear=True`` (the default, astro) returns the normalized raw CFA mosaic — to be
debayered afterwards with ``Debayer``; ``linear=False`` returns an RGB demosaiced by LibRaw
(terrestrial use). An I/O layer, not a ``Process``.
"""

from __future__ import annotations

import numpy as np

RAW_EXT = (".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf", ".pef", ".srw")


def load_raw(path: str, linear: bool = True) -> np.ndarray:
    """Load a RAW → ``(H, W, C)`` float32 array in [0,1].

    ``linear``: single-channel raw CFA mosaic (to be debayered); otherwise demosaiced RGB.
    """
    import rawpy

    with rawpy.imread(path) as raw:
        if linear:
            # ``raw_image_visible`` = raw sensor (excluding optical borders), ADU scale.
            cfa = raw.raw_image_visible.astype(np.float32)
            white = float(raw.white_level) or float(cfa.max()) or 1.0
            black = float(np.mean(raw.black_level_per_channel)) if hasattr(
                raw, "black_level_per_channel") else 0.0
            cfa = np.clip((cfa - black) / max(white - black, 1e-6), 0.0, 1.0)
            return cfa[:, :, np.newaxis]
        rgb = raw.postprocess(
            gamma=(1, 1), no_auto_bright=True, output_bps=16, use_camera_wb=True
        ).astype(np.float32)
        return np.clip(rgb / 65535.0, 0.0, 1.0)
