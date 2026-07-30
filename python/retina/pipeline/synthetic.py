"""Synthetic raw frame generator — the pipeline's test dataset.

Batch pre-processing cannot be tested without a folder of raw frames. Rather than a set of
committed binary files (heavy, opaque, unverifiable), we generate on demand a small folder
whose **ground truth we know**: bias level, dark current, vignetting, positions of the stars
and of the hot pixels. Tests can therefore assert that calibration removed exactly what it
had to.

The generator lives in the package rather than in ``scripts/`` because it has four
consumers: pytest, the server tests, the Playwright smoke test (which calls it through the
console, ``from retina.pipeline.synthetic import make_dataset``) and the console demo. A
script under ``scripts/`` would be a fifth caller, not the source.

Image formation model, in the order in which the pipeline undoes it:

    light = (sky + stars) · vignetting + bias + current·exposure + hot pixels + noise
    flat  = uniform field · vignetting + bias + noise
    dark  = bias + current·exposure + hot pixels + noise
    bias  = constant level + read noise

Two files come out **deliberately** without ``IMAGETYP``: they exercise the fallback on the
name heuristics of :mod:`retina.pipeline.scan`, which is the most frequent real case.

The ``framing`` mode adds the one thing a synthetic dataset could not say until then: a
smart telescope sweep, whose subs differ only by their **pointing** — two mosaic panels
that, without detection, would fall into a single group.
"""

from __future__ import annotations

import math
import os

import numpy as np

from ..i18n import translate as _t

#: geometry: wide enough for star detection and astroalign's triangle matching to converge,
#: small enough for a complete pipeline to run in seconds.
SIZE = 128
STAR_COUNT = 24
STAR_SIGMA = 1.6

BIAS_LEVEL = 0.08
READ_NOISE = 0.0015
DARK_CURRENT = 0.004  # per second
SKY_LEVEL = 0.05
FLAT_LEVEL = 0.40
LIGHT_EXPOSURE = 5.0
DARK_EXPOSURE = 5.0
FLAT_EXPOSURE = 1.0
TEMPERATURE = -10.0
GAIN = 120.0

#: hot pixels, at the same coordinates in darks and lights — the cosmetic correction must
#: make them disappear.
HOT_PIXELS = ((17, 23), (40, 91), (63, 64), (77, 12), (100, 55), (110, 118), (5, 105), (95, 30))
HOT_AMPLITUDE = 0.45

#: pointing offsets (dithering) applied to the lights, in whole pixels: an integer offset
#: guarantees that alignment recovers a clean similarity, without interpolation.
DITHER = ((0, 0), (3, -2), (-2, 3), (1, 2))

BAYER_PATTERN = "RGGB"
#: per-color gains, so that debayering produces a verifiable colored image
_BAYER_GAIN = {"R": 1.0, "G": 0.85, "B": 0.7}

#: pointing of the target (M31), in decimal degrees — written into the lights of every mode.
#: The common case (a single pointing) has to be represented: it is what proves that mosaic
#: detection changes nothing when there is no mosaic.
TARGET_RA = 10.6847
TARGET_DEC = 41.2687

#: **on-sky** offsets of the ``framing`` mode panels, in degrees: two panels side by side in
#: right ascension. 0.8° is the order of magnitude of a Seestar S50 mosaic step (field
#: ≈ 0.7° × 1.3°, overlap included) — well above the
#: :data:`retina.pipeline.groups.PANEL_SEPARATION` threshold, as in reality.
FRAMING_PANELS = ((0.0, 0.0), (0.8, 0.0))
#: pointing spread inside a panel (dithering + re-centering), in degrees: 18″, two orders of
#: magnitude below the separation threshold.
POINTING_JITTER = 0.005


def _vignette() -> np.ndarray:
    """Gentle radial vignetting: 1.0 at the center, ~0.85 in the corners."""
    ys, xs = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32)
    centre = (SIZE - 1) / 2.0
    r2 = ((ys - centre) ** 2 + (xs - centre) ** 2) / (2 * centre**2)
    return (1.0 - 0.15 * r2).astype(np.float32)


def _star_field(rng: np.random.Generator) -> np.ndarray:
    """Field of Gaussian stars — positions and fluxes drawn once, then frozen."""
    field = np.zeros((SIZE, SIZE), dtype=np.float32)
    ys, xs = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32)
    # margin: the stars stay inside the frame despite the dithering
    positions = rng.uniform(10, SIZE - 10, size=(STAR_COUNT, 2))
    fluxes = rng.uniform(0.12, 0.65, size=STAR_COUNT)
    for (y0, x0), flux in zip(positions, fluxes, strict=True):
        field += flux * np.exp(-((ys - y0) ** 2 + (xs - x0) ** 2) / (2 * STAR_SIGMA**2))
    return field


def _hot_mask() -> np.ndarray:
    mask = np.zeros((SIZE, SIZE), dtype=np.float32)
    for y, x in HOT_PIXELS:
        mask[y, x] = HOT_AMPLITUDE
    return mask


def _bayer_gain() -> np.ndarray:
    """RGGB gain map, applied to the lights to simulate a color sensor."""
    gain = np.empty((SIZE, SIZE), dtype=np.float32)
    gain[0::2, 0::2] = _BAYER_GAIN["R"]
    gain[0::2, 1::2] = _BAYER_GAIN["G"]
    gain[1::2, 0::2] = _BAYER_GAIN["G"]
    gain[1::2, 1::2] = _BAYER_GAIN["B"]
    return gain


def _sexagesimal(value: float, *, hours: bool) -> str:
    """Decimal angle → ``"HH MM SS.ss"`` (hours) or ``"+DD MM SS.ss"`` (degrees).

    This is the ``OBJCTRA``/``OBJCTDEC`` spelling (SharpCap, N.I.N.A., ASIAIR); the
    ``framing`` mode uses it so that header reading is exercised on both conventions,
    sexagesimal here and decimal (``RA``/``DEC``) elsewhere.
    """
    signed = "-" if value < 0 else "+"
    total = abs(value) / 15.0 if hours else abs(value)
    whole = int(total)
    minutes = int((total - whole) * 60.0)
    seconds = (total - whole - minutes / 60.0) * 3600.0
    prefix = "" if hours else signed
    return f"{prefix}{whole:02d} {minutes:02d} {seconds:05.2f}"


def _panel_center(panel: int) -> tuple[float, float]:
    """Nominal ``(RA, Dec)`` of the panel, in degrees.

    The offset is given **on the sky**: converting it into right ascension requires dividing
    it by ``cos δ``, failing which a mosaic at high declination would be far more spread out
    than announced.
    """
    sky_delta, delta_dec = FRAMING_PANELS[panel]
    dec = TARGET_DEC + delta_dec
    return (TARGET_RA + sky_delta / math.cos(math.radians(dec)), dec)


def _pointing(panel: int, index: int) -> tuple[float, float]:
    """``(RA, Dec)`` in degrees of the ``index``-th sub of panel ``panel``.

    The subs of a single panel do not aim at exactly the same point: dithering and
    re-centering spread them by :data:`POINTING_JITTER`, far below the separation threshold
    — which is precisely what the detection must ignore.
    """
    ra, dec = _panel_center(panel)
    dec += POINTING_JITTER * ((index % 3) - 1)
    return (ra + POINTING_JITTER * ((index % 2) - 0.5) / math.cos(math.radians(dec)), dec)


def _write(path: str, data: np.ndarray, keywords: dict) -> str:
    from ..io.fits import save_fits
    from ..model.image import Image

    frame = np.clip(data, 0.0, 1.0).astype(np.float32)[:, :, np.newaxis]
    save_fits(path, Image(np.ascontiguousarray(frame)), keywords)
    return path


def _base_keywords(kind: str, exposure: float) -> dict:
    return {
        "IMAGETYP": kind,
        "EXPTIME": exposure,
        "XBINNING": 1,
        "YBINNING": 1,
        "SET-TEMP": TEMPERATURE,
        "CCD-TEMP": TEMPERATURE + 0.2,
        "GAIN": GAIN,
        "INSTRUME": "Retina Synthetic",
    }


def make_dataset(root: str, mode: str = "mono", *, seed: int = 0,
                 filters: tuple[str, ...] = ("L", "R")) -> dict[str, list[str]]:
    """Writes a set of raw frames into ``root``. Returns ``{type: [paths]}``.

    ``mode="mono"`` produces lights and flats per filter; ``mode="osc"`` a single color
    sensor (RGGB matrix, ``BAYERPAT`` keyword), without filters; ``mode="framing"`` a smart
    telescope sweep — **two** mosaic panels that nothing distinguishes but the pointing,
    written in sexagesimal (``OBJCTRA``/``OBJCTDEC``).

    >>> from retina.pipeline.synthetic import make_dataset
    >>> files = make_dataset("/tmp/raws", "mono")
    >>> sorted(files)
    ['bias', 'dark', 'flat', 'light']
    """
    modes = ("mono", "osc", "framing")
    if mode not in modes:
        raise ValueError(_t("unknown mode: {mode!r} (expected one of: {modes})").format(
            mode=mode, modes=", ".join(modes)))
    os.makedirs(root, exist_ok=True)
    rng = np.random.default_rng(seed)
    cutout = _vignette()
    stars = _star_field(rng)
    hot = _hot_mask()
    gain = _bayer_gain() if mode == "osc" else 1.0
    active_filters: tuple[str | None, ...] = (
        (None,) if mode in ("osc", "framing") else filters)
    panels = tuple(range(len(FRAMING_PANELS))) if mode == "framing" else (0,)

    def noise() -> np.ndarray:
        return rng.normal(0.0, READ_NOISE, (SIZE, SIZE)).astype(np.float32)

    out: dict[str, list[str]] = {"bias": [], "dark": [], "flat": [], "light": []}

    for i in range(3):
        keywords = _base_keywords("Bias Frame", 0.0)
        out["bias"].append(_write(
            os.path.join(root, f"bias_{i + 1:03d}.fits"),
            BIAS_LEVEL + noise(), keywords))

    for i in range(3):
        keywords = _base_keywords("Dark Frame", DARK_EXPOSURE)
        if i == 2:
            # without IMAGETYP: the scan must fall back on the file name
            keywords.pop("IMAGETYP")
        out["dark"].append(_write(
            os.path.join(root, f"dark_{DARK_EXPOSURE:g}s_{i + 1:03d}.fits"),
            BIAS_LEVEL + DARK_CURRENT * DARK_EXPOSURE + hot + noise(), keywords))

    for name in active_filters:
        for i in range(3):
            keywords = _base_keywords("Flat Field", FLAT_EXPOSURE)
            if name:
                keywords["FILTER"] = name
            if i == 2 and name == active_filters[0]:
                keywords.pop("IMAGETYP")
            suffix = f"_{name}" if name else ""
            out["flat"].append(_write(
                os.path.join(root, f"flat{suffix}_{i + 1:03d}.fits"),
                FLAT_LEVEL * cutout + BIAS_LEVEL + noise(), keywords))

    for name in active_filters:
        for panel in panels:
            for i, (dy, dx) in enumerate(DITHER):
                keywords = _base_keywords("Light Frame", LIGHT_EXPOSURE)
                keywords["OBJECT"] = "Synthetic"
                if name:
                    keywords["FILTER"] = name
                if mode == "osc":
                    keywords["BAYERPAT"] = BAYER_PATTERN
                ra, dec = _pointing(panel, i)
                if mode == "framing":
                    keywords["OBJCTRA"] = _sexagesimal(ra, hours=True)
                    keywords["OBJCTDEC"] = _sexagesimal(dec, hours=False)
                else:
                    keywords["RA"], keywords["DEC"] = ra, dec
                sky = np.roll(np.roll(stars, dy, axis=0), dx, axis=1) + SKY_LEVEL
                signal = sky * cutout * gain
                frame = signal + BIAS_LEVEL + DARK_CURRENT * LIGHT_EXPOSURE + hot + noise()
                suffix = f"_{name}" if name else ""
                # The panel number is in the name for human inspection only: detection reads
                # only the header, never the file name.
                panel_suffix = f"_p{panel + 1}" if mode == "framing" else ""
                out["light"].append(_write(
                    os.path.join(root, f"light{suffix}{panel_suffix}_{i + 1:03d}.fits"),
                    frame, keywords))

    return out


def truth(mode: str = "mono") -> dict[str, object]:
    """Ground truth of the generated dataset — what tests compare to the calibrated result."""
    return {
        "size": SIZE,
        "bias_level": BIAS_LEVEL,
        "dark_level": BIAS_LEVEL + DARK_CURRENT * DARK_EXPOSURE,
        "sky_level": SKY_LEVEL,
        "hot_pixels": HOT_PIXELS,
        "dither": DITHER,
        "filters": (None,) if mode in ("osc", "framing") else ("L", "R"),
        "vignette_map": _vignette(),
        # nominal centers of the panels (without the pointing jitter), in the order in which
        # grouping must number them — empty outside framing mode.
        "panels": tuple(_panel_center(p) for p in range(len(FRAMING_PANELS)))
        if mode == "framing" else (),
    }
