"""Local AI layer — ONNX models executed on the user's machine.

Pure domain: nothing here knows about the shell, and ``onnxruntime`` stays a **lazy** import
(the ``[ai]`` extra). Two modules, two responsibilities:

- :mod:`retina.ai.onnx` — run a model on an image: session, tiling, feathering. The code lived
  in ``StarRemoval`` and served only it; it is here because network denoising and
  deconvolution have exactly the same need.
- :mod:`retina.ai.models` — know **which** models exist, where they are, and fetch them:
  versioned manifest, cache under ``cache_dir()/models/``, verified download.

No model is bundled in the wheel — a matter of weight and of license. The repository
distributes only the manifest, which points at the projects' official URLs.
"""

from __future__ import annotations

from .models import ModelSpec, available, download, ensure, is_downloaded, model_path
from .onnx import feather, open_session, run_tiled

__all__ = [
    "ModelSpec",
    "available",
    "download",
    "ensure",
    "feather",
    "is_downloaded",
    "model_path",
    "open_session",
    "run_tiled",
]
