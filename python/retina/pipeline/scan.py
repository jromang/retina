"""Scanning a folder of raw frames and classifying them.

First step of the batch pre-processing workflow: walk a folder, read **the headers alone**
(:func:`retina.io.fits.load_fits_header` — never the pixels) and deduce for each file its
type (light/dark/flat/bias), its filter, its exposure, its binning, its temperature and its
gain.

Two sources of information, in this order:

1. the **FITS keywords** (``IMAGETYP``, ``FILTER``, ``EXPTIME``…), with the aliases and
   spellings met in the wild ("Dark Frame", "FLAT", ``SET-TEMP`` vs
   ``CCD-TEMP``);
2. the **file name**, as a fallback — many acquisitions lose their headers on the way
   through a converter.

The header also gives the mount **pointing** (:func:`pointing`), which grouping uses to
separate the panels of a mosaic — a smart telescope in "framing mode" sweeps several
pointings without changing anything else in its headers.

Each :class:`FrameInfo` keeps in ``source`` where its classification came from. That is what
lets the user (console or wizard) spot and correct a dubious deduction: we never guess in
silence, an unclassified file stays ``kind="unknown"``.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field

from ..i18n import translate as _t

# Candidate extensions. RAW files are accepted (DSLR lights) but carry no FITS header:
# they are classified from the file name alone.
FITS_EXT = (".fits", ".fit", ".fts")
KINDS = ("light", "dark", "flat", "bias", "unknown")

#: ``IMAGETYP`` values met in the wild → our vocabulary. The key is normalized
#: (lowercase, separators stripped) before comparison.
_IMAGETYP_ALIASES = {
    "light": "light", "lightframe": "light", "science": "light", "object": "light",
    "dark": "dark", "darkframe": "dark",
    "flat": "flat", "flatframe": "flat", "flatfield": "flat",
    "bias": "bias", "biasframe": "bias", "offset": "bias", "zero": "bias",
    # A flat-dark stays a dark: grouping (by exposure) is what will associate it with the
    # flats. We do not create a fifth type for that.
    "darkflat": "dark", "flatdark": "dark",
    # masters already built, dropped back into a folder of raw frames
    "masterbias": "bias", "masterdark": "dark", "masterflat": "flat",
    "masterlight": "light",
}

#: pattern that detects an **already built** master. Looked for in the file name and its
#: immediate folder — master libraries live in a dedicated folder
#: (``masters/dark_300s.fits``) — but **no further**: a working folder named
#: ``master_project/`` would otherwise make all its raw frames pass for masters, which
#: happened on the first try. Never applied to lights either, the usual rule: an object
#: named "Master" must not contaminate its subs.
_MASTER_PATTERN = re.compile(r"master", re.IGNORECASE)


def _looks_like_master(path: str) -> bool:
    parts = os.path.normpath(path).split(os.sep)
    return any(_MASTER_PATTERN.search(part) for part in parts[-2:])

#: file name patterns, tested in order (the first match wins).
#: `bias`/`offset` before `dark`: a "bias_dark_001" is a bias. The plural is accepted
#: ("darks/", "flats/"): acquisition folders almost always carry it.
_PLURAL = r"(?:e?s)?"
_NAME_PATTERNS: tuple[tuple[str, str], ...] = (
    (rf"(?:^|[^a-z])(?:bias|offset|zero){_PLURAL}(?:[^a-z]|$)", "bias"),
    (rf"(?:^|[^a-z])(?:flat[-_ ]?dark|dark[-_ ]?flat){_PLURAL}(?:[^a-z]|$)", "dark"),
    (rf"(?:^|[^a-z])(?:dark){_PLURAL}(?:[^a-z]|$)", "dark"),
    (rf"(?:^|[^a-z])(?:flat){_PLURAL}(?:[^a-z]|$)", "flat"),
    (rf"(?:^|[^a-z])(?:light|science){_PLURAL}(?:[^a-z]|$)", "light"),
)

#: Keywords that describe the **rig** and enter the identity of a group. Two telescopes
#: carrying the same camera produce frames of the same geometry and the same binning:
#: nothing would tell them apart without this, and their flats would be mixed although
#: they describe different optics.
#:
#: ``SESSION`` is **not** here: it is a temporal dimension, and splitting by night would
#: prevent integrating two nights of the same object together — the opposite of what we
#: want. Whoever wants per-night masters adds it explicitly.
IDENTITY_KEYWORDS = ("INSTRUME", "TELESCOP")

#: usual filters recognized in a file name, as a last resort.
_NAME_FILTERS = ("ha", "sii", "oiii", "lum", "l", "r", "g", "b", "s", "o", "h")


def _norm(value: object) -> str:
    """Lowercase without separators — "Dark Frame" and "DARK_FRAME" meet up."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _as_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _section(value: object) -> str | None:
    """A plausible IRAF section, or ``None`` — a header can carry anything at all."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text.startswith("[") and text.endswith("]") else None


def _first(keywords: dict, *names: str) -> object | None:
    """First key present and non-empty among ``names`` (case-insensitive)."""
    lowered = {str(k).lower(): v for k, v in keywords.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None and str(value).strip() != "":
            return value
    return None


def _sexagesimal(value: str) -> float | None:
    """``"10 43 25.0"``, ``"10:43:25"``, ``"+41d16m09s"`` → decimal value, or ``None``.

    The unit is that of the first field: it is the caller that knows whether these are hours
    (right ascension) or degrees (declination).
    """
    text = str(value).strip().replace(",", ".")
    signed = -1.0 if text.startswith("-") else 1.0
    fields = [c for c in re.split(r"[^0-9.]+", text.lstrip("+-")) if c]
    if not fields:
        return None
    try:
        values = [float(c) for c in fields[:3]]
    except ValueError:
        return None
    total = 0.0
    for rank, part in enumerate(values):
        total += part / (60.0**rank)
    return signed * total


def _angle(value: object, *, hours: bool) -> float | None:
    """Angle in **decimal degrees**, or ``None``.

    A number is already in degrees (the ``RA``/``DEC``/``CRVAL*`` convention); a sexagesimal
    string is in **hours** for right ascension (the SharpCap/N.I.N.A. ``OBJCTRA``
    convention: ``"10 43 25.00"``) and in degrees for declination.
    """
    if value is None:
        return None
    direct = _as_float(value)
    if direct is not None:
        return direct
    decimal = _sexagesimal(str(value))
    if decimal is None:
        return None
    return decimal * 15.0 if hours else decimal


def pointing(keywords: dict) -> tuple[float | None, float | None]:
    """``(RA, Dec)`` in decimal degrees, or ``(None, None)`` — the frame's pointing.

    Three sources, in order: ``RA``/``DEC`` (degrees, the most widespread),
    ``OBJCTRA``/``OBJCTDEC`` (sexagesimal) and ``CRVAL1``/``CRVAL2`` (already solved frame).
    An out-of-range value is rejected rather than corrected: a wrong pointing is worth less
    than a missing pointing, which is visible.
    """
    # Any right ascension written in sexagesimal is in hours, whatever the keyword; written
    # as a number, it is in degrees. That is what `hours=True` distinguishes.
    ra = _angle(_first(keywords, "RA", "OBJCTRA", "CRVAL1"), hours=True)
    dec = _angle(_first(keywords, "DEC", "OBJCTDEC", "CRVAL2"), hours=False)
    if ra is not None:
        ra = ra % 360.0 if -360.0 <= ra <= 360.0 else None
    if dec is not None and not -90.0 <= dec <= 90.0:
        dec = None
    return (ra, dec)


@dataclass
class FrameInfo:
    """An inventoried frame: its path and what could be deduced from it."""

    path: str
    kind: str = "unknown"
    filter: str | None = None
    exposure: float | None = None
    binning: int = 1
    temperature: float | None = None
    gain: float | None = None
    #: geometry, read from NAXIS1/NAXIS2 — a **hard** grouping criterion: applying a master
    #: of a different size is the mistake that ruins a whole night.
    width: int | None = None
    height: int | None = None
    #: values of the rig identity keywords (see :data:`IDENTITY_KEYWORDS`). Carried along
    #: with the frame: grouping uses them, and the wizard works on a serialized inventory,
    #: without the raw keywords.
    extra: dict = field(default_factory=dict)
    #: IRAF sections declared by the acquisition: overscan area and useful area. Read from
    #: the header rather than configured by hand — it is a standard convention, and having
    #: it entered sensor by sensor would be an admission of defeat.
    biassec: str | None = None
    trimsec: str | None = None
    #: an **already built** master, supplied by the user: we reuse it as is instead of
    #: making one. See :data:`_MASTER_PATTERN`.
    is_master: bool = False
    #: Bayer matrix pattern (``RGGB``…) if the sensor is color, otherwise ``None``.
    #: Carried along with the frame: it is what decides the debayering step, and the wizard
    #: works on a serialized inventory, without the raw keywords.
    bayer: str | None = None
    #: mount pointing, in decimal degrees (``None`` if the header carries none).
    #: Read for every frame, but only meaningful for lights: it is what separates the
    #: **panels of a mosaic** (see
    #: :func:`retina.pipeline.groups.detect_panels`). A dark or a bias sometimes carries the
    #: pointing of the previous sub — grouping never uses it.
    ra: float | None = None
    dec: float | None = None
    #: where ``kind`` comes from: ``header`` | ``filename`` | ``default`` | ``user``.
    #: Traceability — the wizard displays the column and allows correcting without re-reading
    #: the files; a corrected frame moves to ``user`` and stops being flagged as guessed.
    source: str = "default"
    #: set aside from processing by the user. Reversible, and deliberately distinct from
    #: ``kind="unknown"``: an excluded frame **is** classified, we simply do not want it
    #: (cloud, satellite, missed focus). Grouping ignores it.
    excluded: bool = False
    #: raw keywords, kept for the plan (BAYERPAT) and for inspection.
    keywords: dict = field(default_factory=dict, repr=False)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def to_dict(self) -> dict:
        """Transportable form (RPC, JSON) — without the raw keywords, too bulky."""
        data = asdict(self)
        data.pop("keywords")
        return data

    @classmethod
    def from_dict(cls, data: dict) -> FrameInfo:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known.pop("keywords", None)
        known["extra"] = dict(known.get("extra") or {})
        return cls(**known)


@dataclass
class Inventory:
    """The result of a :func:`scan`: the root that was walked and its frames."""

    root: str
    frames: list[FrameInfo] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.frames)

    def __iter__(self):
        return iter(self.frames)

    def of_kind(self, kind: str) -> list[FrameInfo]:
        return [f for f in self.frames if f.kind == kind]

    def counts(self) -> dict[str, int]:
        """``{type: count}`` — the summary the CLI and the wizard display."""
        out = dict.fromkeys(KINDS, 0)
        for frame in self.frames:
            out[frame.kind] = out.get(frame.kind, 0) + 1
        return {k: v for k, v in out.items() if v}

    @property
    def is_osc(self) -> bool:
        """True if the lights carry a Bayer matrix (one-shot color sensor)."""
        return any(f.bayer for f in self.frames if f.kind == "light")

    @property
    def bayer_pattern(self) -> str | None:
        """Bayer pattern of the lights, if there is one."""
        return next((f.bayer for f in self.frames if f.kind == "light" and f.bayer), None)

    def groups(self, **tolerances):
        """Homogeneous groups — see :func:`retina.pipeline.groups.group_frames`."""
        from .groups import group_frames

        return group_frames(self.frames, **tolerances)

    def to_dict(self) -> dict:
        return {"root": self.root, "frames": [f.to_dict() for f in self.frames]}

    @classmethod
    def from_dict(cls, data: dict) -> Inventory:
        return cls(
            root=data.get("root", ""),
            frames=[FrameInfo.from_dict(f) for f in data.get("frames", [])],
        )

    def __repr__(self) -> str:
        counts = ", ".join(f"{k}={v}" for k, v in self.counts().items())
        return f"Inventory({self.root!r}, {len(self.frames)} frames: {counts or 'none'})"


# --- classification ------------------------------------------------------------------

def kind_from_keywords(keywords: dict) -> str | None:
    """Type deduced from ``IMAGETYP``, or ``None`` if the keyword is missing/unknown."""
    value = _first(keywords, "IMAGETYP", "IMGTYPE", "OBSTYPE", "FRAMETYP")
    if value is None:
        return None
    return _IMAGETYP_ALIASES.get(_norm(value))


def kind_from_name(path: str) -> str | None:
    """Type deduced from the file name **and from its parent folders**, or ``None``.

    Folders count: a ``M31/darks/img_001.fits`` tree is the most common case of an
    acquisition without a usable header. The file name takes precedence over the folder.
    """
    parts = os.path.normpath(path).split(os.sep)
    for part in reversed(parts):  # file first, then folders on the way up
        # "masterDark_300s": the word is glued to the prefix, and the patterns require a
        # boundary. We detach it rather than loosen the patterns, which would then
        # recognize "nodark" or "redarkened".
        lowered = _MASTER_PATTERN.sub(" ", part.lower())
        for pattern, kind in _NAME_PATTERNS:
            if re.search(pattern, lowered):
                return kind
    return None


def _exposure_from_name(name: str) -> float | None:
    """Exposure extracted from a "_300s_", "1.5sec", "300s" in the file name."""
    match = re.search(r"(?:^|[^0-9a-z])(\d+(?:[.,]\d+)?)\s*s(?:ec|econds?)?(?:[^a-z]|$)",
                      name.lower())
    return float(match.group(1).replace(",", ".")) if match else None


def _binning_from_name(name: str) -> int | None:
    match = re.search(r"bin[-_ ]?([1-4])(?:x[1-4])?", name.lower())
    return int(match.group(1)) if match else None


def _filter_from_name(name: str) -> str | None:
    """Filter recognized between separators (``M31_Ha_001.fits`` → ``Ha``)."""
    tokens = re.split(r"[^a-zA-Z0-9]+", os.path.splitext(name)[0])
    for token in tokens:
        if token.lower() in _NAME_FILTERS:
            return token.upper()
    return None


def classify(path: str, keywords: dict | None = None,
             identity: tuple[str, ...] = IDENTITY_KEYWORDS) -> FrameInfo:
    """Builds a :class:`FrameInfo` for ``path``, headers already read or not."""
    if keywords is None:
        keywords = read_keywords(path)
    name = os.path.basename(path)

    kind = kind_from_keywords(keywords)
    source = "header"
    if kind is None:
        kind = kind_from_name(path)
        source = "filename" if kind else "default"
    if kind is None:
        # A DSLR RAW has no FITS header and is never a master: we assume light.
        from ..io.raw import RAW_EXT

        if os.path.splitext(path)[1].lower() in RAW_EXT:
            kind, source = "light", "default"
        else:
            kind = "unknown"

    exposure = _as_float(_first(keywords, "EXPTIME", "EXPOSURE", "EXPOSED"))
    if exposure is None:
        exposure = _exposure_from_name(name)

    binning = _as_float(_first(keywords, "XBINNING", "BINX", "CCDBIN1"))
    if binning is None:
        from_name = _binning_from_name(name)
        binning = float(from_name) if from_name is not None else 1.0

    # SET-TEMP is the set point, CCD-TEMP the measurement: the set point first, it is stable
    # from one frame to the next where the measurement wanders by a few tenths.
    temperature = _as_float(_first(keywords, "SET-TEMP", "SETTEMP", "CCD-TEMP", "CCDTEMP",
                                   "TEMPERAT"))

    filter_name = _first(keywords, "FILTER", "FILTER1", "FILT")
    filter_name = str(filter_name).strip() if filter_name is not None else None
    if filter_name is None and kind in ("light", "flat"):
        filter_name = _filter_from_name(name)

    width = _as_float(_first(keywords, "NAXIS1"))
    height = _as_float(_first(keywords, "NAXIS2"))
    bayer = _first(keywords, "BAYERPAT", "COLORTYP", "XBAYROFF")
    bayer = str(bayer).strip().upper() if bayer is not None else None
    if bayer not in ("RGGB", "BGGR", "GRBG", "GBRG"):
        bayer = None

    ra, dec = pointing(keywords)

    return FrameInfo(
        path=path,
        kind=kind,
        filter=filter_name,
        exposure=exposure,
        binning=int(binning),
        temperature=temperature,
        gain=_as_float(_first(keywords, "GAIN", "EGAIN", "ISOSPEED")),
        width=int(width) if width else None,
        height=int(height) if height else None,
        bayer=bayer,
        ra=ra,
        dec=dec,
        biassec=_section(_first(keywords, "BIASSEC", "OVRSCAN")),
        trimsec=_section(_first(keywords, "TRIMSEC", "DATASEC")),
        is_master=kind != "light" and _looks_like_master(path),
        extra={keyword: str(_first(keywords, keyword)).strip() for keyword in identity
               if _first(keywords, keyword) is not None},
        source=source,
        keywords=keywords,
    )


def read_keywords(path: str) -> dict:
    """A file's header, or ``{}`` if it has none (RAW) or if it is unreadable."""
    if os.path.splitext(path)[1].lower() not in FITS_EXT:
        return {}
    from ..io.fits import load_fits_header

    try:
        return load_fits_header(path)
    except Exception:
        # A truncated or non-FITS file despite its extension must not break the scan of a
        # 500-frame folder: it will fall back on the name heuristics.
        return {}


def scan(path: str, *, recursive: bool = True,
         identity: tuple[str, ...] = IDENTITY_KEYWORDS) -> Inventory:
    """Inventories the frames of a folder (or a single file).

    >>> inv = retina.pipeline.scan("/data/M31")
    >>> inv.counts()
    {'light': 40, 'dark': 20, 'flat': 15, 'bias': 30}
    """
    from ..io.raw import RAW_EXT

    accepted = FITS_EXT + RAW_EXT
    if os.path.isfile(path):
        return Inventory(root=os.path.dirname(os.path.abspath(path)),
                         frames=[classify(os.path.abspath(path), identity=identity)])
    if not os.path.isdir(path):
        raise ValueError(_t("Folder not found: {path}").format(path=path))

    root = os.path.abspath(path)
    files: list[str] = []
    if recursive:
        for current, dirs, names in os.walk(root):
            # pipeline outputs are not raw frames: we do not re-scan ourselves
            dirs[:] = sorted(d for d in dirs if d != OUTPUT_DIR_NAME and not d.startswith("."))
            files += [os.path.join(current, n) for n in sorted(names)
                      if os.path.splitext(n)[1].lower() in accepted]
    else:
        files = [os.path.join(root, n) for n in sorted(os.listdir(root))
                 if os.path.splitext(n)[1].lower() in accepted
                 and os.path.isfile(os.path.join(root, n))]

    return Inventory(root=root, frames=[classify(f, identity=identity) for f in files])


# --- manual corrections ----------------------------------------------------------------
#
# Classification is a deduction: it gets things wrong, and the ``source`` field is there to
# say so. These two functions are the counterpart — what it takes to settle the doubt. They
# are **named domain operations**, not plain attribute assignments, because the wizard must
# be able to echo them: correcting a type with the mouse writes into the console the Python
# line that would have done it (the console/GUI parity rule).
#
# They work by **file paths**, never by group: a group is only an aggregation recomputed at
# each call, and the most useful case — an ``unknown`` frame — precisely belongs to no
# group at all.


def _index(inventory: Inventory) -> dict[str, FrameInfo]:
    """Frames indexed by path, normalized form included (the client may send back a path
    re-serialized through JSON, with different separators under Windows)."""
    index: dict[str, FrameInfo] = {}
    for frame in inventory.frames:
        index.setdefault(frame.path, frame)
        index.setdefault(os.path.normpath(frame.path), frame)
    return index


def _named(inventory: Inventory, paths) -> list[FrameInfo]:
    if isinstance(paths, str):
        paths = [paths]
    index = _index(inventory)
    frames = []
    for path in paths:
        frame = index.get(path) or index.get(os.path.normpath(path))
        if frame is None:
            raise ValueError(_t("Frame not in inventory: {path}").format(path=path))
        frames.append(frame)
    return frames


def reclassify(inventory: Inventory, paths, kind: str) -> Inventory:
    """Corrects the type of frames, and returns the modified inventory.

    >>> inventory = retina.pipeline.reclassify(inventory, ["/data/img_01.fits"], "flat")

    The affected frames move to ``source="user"``: their type is no longer a deduction, and
    the wizard stops marking them as dubious.
    """
    if kind not in KINDS:
        raise ValueError(_t("Unknown type: {kind!r} (expected: {kinds})").format(
            kind=kind, kinds=", ".join(KINDS)))
    for frame in _named(inventory, paths):
        frame.kind = kind
        frame.source = "user"
    return inventory


def exclude(inventory: Inventory, paths, excluded: bool = True) -> Inventory:
    """Sets frames aside (or brings them back), and returns the modified inventory.

    >>> inventory = retina.pipeline.exclude(inventory, plan.results)   # or a list
    >>> inventory = retina.pipeline.exclude(inventory, paths, excluded=False)
    """
    for frame in _named(inventory, paths):
        frame.excluded = bool(excluded)
    return inventory


#: name of the pipeline output folder, ignored by the scan (avoids taking the intermediates
#: of a previous run for raw frames). Defined here because the scan is what needs to know
#: it; the runner imports it.
OUTPUT_DIR_NAME = "retina_pipeline"
