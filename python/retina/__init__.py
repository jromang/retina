"""Retina — astronomical image processing, with a fully scriptable Python core.

Public import: the domain (headless, no shell) and the root application object ``app``.
The web shell lives in ``retina.server`` and is only a client of that same API.
"""

from __future__ import annotations

from .app import Application, app
from .backend import HAS_RUST, backend_name, gaussian_convolve
from .documentation import doc
from .model.image import Image
from .model.stf import STF, ChannelSTF
from .model.view import View
from .model.viewport_state import (
    DISPLAY_CHANNELS,
    InteractionMode,
    MaskDisplayMode,
    ReadoutOptions,
    TransparencyMode,
    ViewportState,
)
from .model.window import ImageWindow, Preview
from .process.base import Parameter, Process
from .process.container import ProcessContainer
from .process.parameters import parameters
from .process.registry import all_processes, get, load_builtin, register

# register the bundled processes (entry points + import fallback) on first import
load_builtin()

# expose the concrete processes at package level (console usage: GaussianConvolution(...))
# … and every other registered process (retina.Deconvolution, retina.Integration, …)
import sys as _sys  # noqa: E402

from . import pipeline  # noqa: E402  (retina.pipeline.scan(...) without an explicit import)
from .processes.convolution import GaussianConvolution  # noqa: E402
from .processes.curves import CurvesTransformation  # noqa: E402
from .processes.histogram import HistogramTransformation  # noqa: E402
from .processes.pixelmath import PixelMath  # noqa: E402

for _name, _cls in all_processes().items():
    setattr(_sys.modules[__name__], _name, _cls)

__version__ = "0.0.1"

__all__ = [
    "DISPLAY_CHANNELS",
    "HAS_RUST",
    "STF",
    "Application",
    "ChannelSTF",
    "CurvesTransformation",
    "GaussianConvolution",
    "HistogramTransformation",
    "Image",
    "ImageWindow",
    "InteractionMode",
    "MaskDisplayMode",
    "Parameter",
    "PixelMath",
    "Preview",
    "Process",
    "ProcessContainer",
    "ReadoutOptions",
    "TransparencyMode",
    "View",
    "ViewportState",
    "__version__",
    "all_processes",
    "app",
    "backend_name",
    "doc",
    "gaussian_convolve",
    "get",
    "load_builtin",
    "parameters",
    "pipeline",
    "register",
]
