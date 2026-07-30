"""PixelMath — a **Python/numpy** expression evaluated on the image, sandboxed (asteval).

Consistent with the "everything is Python" pillar: no home-grown language, we evaluate real
vectorized Python on the ``(H, W, C)`` array, with all of numpy at hand.

- ``img`` (or ``T``) = the complete target image ``(H, W, C)``. Channels: ``img[:, :, 0]``.
- References to other views by **id** (``Image01``, …), resolved through
  :mod:`retina.process.context` (app provider) or ``set_images`` in headless use.
- Coordinates: ``x``, ``y`` (normalized, shape ``(H, W, 1)`` → they broadcast over the
  channels), ``X``, ``Y`` (integer indices), ``width``, ``height``.
- numpy functions (``sqrt, exp, log, log10, sin, where, clip, minimum, maximum, mean,
  median, std, sum, abs, …``) + helpers ``iif`` (= ``where``), ``mtf``, ``mad``, ``rescale``.
- Multiple statements / symbols: write several lines, the last one is the value.
- Output: ``truncate`` (default, clamps to [range_low, range_high]) or ``rescale``;
  ``create_new_image`` to generate a new view (handled by the app).

Examples:
    img * 1.5
    where(img > 0.8, 1.0, img)
    (img - median(img)) * 4 + 0.2
    bg = median(img, axis=(0, 1), keepdims=True)   # background PER channel
    (img - bg) * 3 + 0.25
    (Image01 + Image02) / 2                          # average of two views
"""

from __future__ import annotations

import ast

import numpy as np
from asteval import Interpreter as ASTEval

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


def _mtf(m, x):
    """Midtones Transfer Function (same as the STF)."""
    x = np.asarray(x, dtype=np.float64)
    m = float(np.asarray(m))
    if m <= 0.0:
        return np.ones_like(x)
    if m >= 1.0:
        return np.zeros_like(x)
    if m == 0.5:
        return x
    return np.divide((m - 1.0) * x, (2.0 * m - 1.0) * x - m, out=np.zeros_like(x),
                     where=((2.0 * m - 1.0) * x - m) != 0.0)


def _rescale(x, a=0.0, b=1.0):
    x = np.asarray(x, dtype=np.float64)
    lo, hi = float(x.min()), float(x.max())
    y = (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)
    return y * (b - a) + a


def _mad(a):
    a = np.asarray(a)
    return float(np.median(np.abs(a - np.median(a))))


def _spatial(fn, kw):
    """Applies a scipy.ndimage filter per channel (2D), preserving (H, W, C)."""
    def f(a, s):
        a = np.asarray(a, dtype=np.float64)
        if a.ndim == 3:
            return np.stack([fn(a[:, :, c], **{kw: s}) for c in range(a.shape[2])], axis=2)
        return fn(a, **{kw: s})
    return f


def _namespace(shape: tuple[int, int, int], rng) -> dict:
    h, w = shape[0], shape[1]
    xn = (np.arange(w, dtype=np.float64) / max(w - 1, 1))[None, :, None]
    yn = (np.arange(h, dtype=np.float64) / max(h - 1, 1))[:, None, None]
    ns = {
        # helpers not provided directly by asteval/numpy
        "iif": np.where, "mtf": _mtf, "rescale": _rescale, "mad": _mad,
        "clip": np.clip, "where": np.where,
        "minimum": np.minimum, "maximum": np.maximum,
        "median": np.median, "mean": np.mean, "std": np.std, "var": np.var,
        "percentile": lambda a, q: np.percentile(a, q),
        # handy constructors (per-channel constants: img * array([r, g, b]))
        "array": np.array, "arange": np.arange,
        "zeros_like": np.zeros_like, "ones_like": np.ones_like,
        # Fourier transform (numpy)
        "fft2": lambda a: np.fft.fft2(a, axes=(0, 1)),
        "ifft2": lambda a: np.fft.ifft2(a, axes=(0, 1)),
        "fftshift": np.fft.fftshift, "real": np.real, "imag": np.imag, "conj": np.conj,
        # coordinates / geometry (shapes broadcastable over the channels)
        "x": np.broadcast_to(xn, (h, w, 1)).copy(),
        "y": np.broadcast_to(yn, (h, w, 1)).copy(),
        "X": np.broadcast_to((np.arange(w, dtype=np.float64))[None, :, None], (h, w, 1)).copy(),
        "Y": np.broadcast_to((np.arange(h, dtype=np.float64))[:, None, None], (h, w, 1)).copy(),
        "width": w, "height": h,
        "pi": np.pi, "e": np.e,
        "rand": lambda: rng.random((h, w, 1)),
        "gauss": lambda m=0.0, s=1.0: rng.normal(m, s, (h, w, 1)),
    }
    # spatial filters (scipy) — neighborhood, not only per pixel
    try:
        from scipy.ndimage import (
            gaussian_filter,
            maximum_filter,
            median_filter,
            minimum_filter,
            uniform_filter,
        )

        ns.update({
            "gaussian": _spatial(gaussian_filter, "sigma"),
            "median_filter": _spatial(median_filter, "size"),
            "uniform_filter": _spatial(uniform_filter, "size"),
            "maximum_filter": _spatial(maximum_filter, "size"),
            "minimum_filter": _spatial(minimum_filter, "size"),
        })
    except Exception:  # scipy missing (without the [astro] extra): keep the rest
        pass
    # robust estimators (astropy)
    try:
        from astropy.stats import biweight_location, mad_std

        ns["mad_std"] = lambda a: float(mad_std(a))
        ns["biweight"] = lambda a: float(biweight_location(a))
    except Exception:
        pass
    return ns


# exposed names (for the syntax highlighting of the PixelMath editor)
PIXELMATH_NAMES = [
    "img", "T", "iif", "mtf", "rescale", "mad", "mad_std", "biweight", "clip", "where",
    "minimum", "maximum", "median", "mean", "std", "var", "percentile", "array", "arange",
    "zeros_like", "ones_like", "fft2", "ifft2", "fftshift", "real", "imag", "conj",
    "gaussian", "median_filter", "uniform_filter", "maximum_filter", "minimum_filter",
    "x", "y", "X", "Y", "width", "height", "pi", "e", "rand", "gauss",
    "sqrt", "exp", "log", "log10", "sin", "cos", "tan", "abs",
]


def _referenced_names(source: str) -> set[str]:
    """Names loaded (not assigned) in the code — candidates to be resolved as images."""
    tree = ast.parse(source, mode="exec")
    stored, loaded = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (stored if isinstance(node.ctx, ast.Store) else loaded).add(node.id)
    return loaded - stored


@register
class PixelMath(Process):
    process_id = "PixelMath"
    category = "PixelMath"
    parameters = [
        Parameter("expression", "text", default="img", label=N_("Expression (Python)")),
        Parameter("symbols", "text", default="", label=N_("Symbols (preamble lines)")),
        Parameter("rescale", "bool", default=False, label=N_("Rescale output")),
        Parameter("truncate", "bool", default=True, label=N_("Truncate")),
        Parameter("range_low", "real", default=0.0, min=0.0, max=1.0, label=N_("Lower bound")),
        Parameter("range_high", "real", default=1.0, min=0.0, max=1.0, label=N_("Upper bound")),
        Parameter("create_new_image", "bool", default=False, label=N_("New image")),
        Parameter("new_image_id", "str", default="", label=N_("New image id")),
        Parameter("seed", "int", default=0, min=0, max=2**31 - 1,
                  label=N_("Seed (rand/gauss)")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._images: dict[str, object] = {}

    def set_images(self, images: dict[str, object]) -> PixelMath:
        """Supplies images referenceable by id (headless/test use)."""
        self._images = dict(images)
        return self

    def _resolve_full(self, name: str):
        if name in self._images:
            img = self._images[name]
            return img.data if hasattr(img, "data") else np.asarray(img)
        from ..process import context

        return context.resolve_image_full(name)

    def _apply(self, data: np.ndarray) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        ns = _namespace(data.shape, rng)
        ns["img"] = data
        ns["T"] = data

        sym = self.symbols.strip()
        expr = self.expression.strip() or "img"
        source = f"{sym}\n{expr}" if sym else expr

        try:
            referenced = _referenced_names(source)
        except SyntaxError as exc:
            raise ValueError(_t("PixelMath: invalid syntax: {error}").format(error=exc)) from exc

        for name in referenced - set(ns):  # resolve the remaining identifiers as images
            arr = self._resolve_full(name)
            if arr is not None:
                ns[name] = arr

        aeval = ASTEval(usersyms=ns)
        try:
            with np.errstate(all="ignore"):
                result = aeval(source, raise_errors=True)
        except Exception as exc:
            raise ValueError(
                _t("PixelMath: \"{expr}\": {error}").format(expr=expr, error=exc)) from exc

        out = np.nan_to_num(np.asarray(result, dtype=np.float32), nan=0.0, posinf=1.0, neginf=0.0)
        try:
            out = np.broadcast_to(out, data.shape).astype(np.float32).copy()
        except ValueError as exc:
            raise ValueError(
                _t("PixelMath: result of shape {shape} not broadcastable to {target}").format(
                    shape=out.shape, target=data.shape)
            ) from exc
        return self._finalize(out)

    def _finalize(self, out: np.ndarray) -> np.ndarray:
        lo, hi = float(self.range_low), float(self.range_high)
        if self.rescale:
            omin, omax = float(out.min()), float(out.max())
            if omax > omin:
                out = (out - omin) / (omax - omin)
            out = out * (hi - lo) + lo
        elif self.truncate:
            out = np.clip(out, lo, hi)
        return out.astype(np.float32)
