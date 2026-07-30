"""Compute backend dispatch — a package, with the original module's API unchanged.

``from retina.backend import gaussian_convolve, backend_name, HAS_RUST`` still holds: the
conversion into a package only moved files around. To it is added :mod:`retina.backend.xp`
(``get_array_module``, ``is_gpu``, ``ndimage_for``, ``to_numpy``) — the "xp" that makes it
possible to write an operator once and run it on numpy as well as on CuPy, the input
deciding. GPU conversions of the processes are done operator by operator, prioritized by
profiling (``scripts/profile_hotspots.py``), never in bulk.
"""

from __future__ import annotations

from .convolve import HAS_RUST, backend_name, gaussian_convolve
from .xp import (
    free_gpu_memory,
    get_array_module,
    gpu_available,
    is_gpu,
    is_oom,
    ndimage_for,
    synchronize,
    to_device,
    to_numpy,
)

__all__ = [
    "HAS_RUST",
    "backend_name",
    "free_gpu_memory",
    "gaussian_convolve",
    "get_array_module",
    "gpu_available",
    "is_gpu",
    "is_oom",
    "ndimage_for",
    "synchronize",
    "to_device",
    "to_numpy",
]
