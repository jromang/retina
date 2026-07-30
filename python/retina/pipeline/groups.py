"""Frame grouping and calibration ↔ lights matching.

A :class:`FrameGroup` gathers interchangeable frames — those a master can be made from, or
that can be integrated together. The rules below follow established practice for batch
pre-processing, whose field experience is hard to guess; the implementation, for its part,
is ours.

# What defines a group

**Hard** criteria, required for every type: same geometry (width × height), same binning,
same **gain**, same rig (``INSTRUME``/``TELESCOP``). Applying a master of another size is
the mistake that ruins a whole night, and it is undetectable after the fact.

Gain deserves to be named: it sets the electrons→ADU conversion, hence the amplitude of the
dark signal *and* the read noise. A master dark built at gain 100 corrects nothing at gain
300 — and the dual-gain rig (narrowband at high gain, RGB at low gain) is common. Rig
identity serves the same purpose: two telescopes carrying the same camera produce frames
indistinguishable by geometry, but incompatible flats.

Then, depending on the type:

===== ========== ============ ===================================================
type  filter?    exposure?    comment
===== ========== ============ ===================================================
light yes        yes (±2 s)   what we integrate together
dark  **no**     yes (±10 s)  the shutter is closed: the filter is meaningless
flat  yes        **no**       auto-brightness flats vary without changing meaning
bias  **no**     **no**       zero exposure
===== ========== ============ ===================================================

Temperature is an additional criterion (wide tolerance), where the usual rule makes it an
optional "grouping keyword": a dark taken at +20 °C does not calibrate a light taken at
−10 °C, and the oversight is frequent.

# The matching

:func:`match_calibration` covers the lights **and** the flats, because flats are calibrated
too. Three rules are worth spelling out, all of them established practice:

**1. The bias enters the chain of a light only if it serves.** A master dark contains the
bias: subtracting it already removes the pedestal. We keep the master bias only if no dark
was found, or if the dark has to be scaled (next case).

**2. Scaling a dark requires extracting its current.** Multiplying a master dark by 0.5
would also multiply its bias, which does not depend on the exposure time. A **dark current**
(master dark minus master bias) is then needed, and calibration proceeds in two steps:
``light − bias − k·dark_current``. That is exactly the ``ImageCalibration`` formula, hence
the ``bias`` and ``dark_scale`` fields. Without a master bias, scaling is refused and the
reason is recorded in ``notes`` rather than producing a wrong calibration.

**3. A flat is calibrated by a flat-dark, otherwise by a bias — never both.** A dark of the
same exposure as the flat (to within ``FLAT_DARK_TOLERANCE``) contains the bias *and* the
current: it suffices on its own. Failing that, the bias alone does the job, a flat's
exposure being too short to accumulate dark current.

# The panels of a mosaic

A smart telescope in "framing mode" (Seestar, Dwarf) sweeps several pointings to cover a
wide field. Nothing tells them apart in the header — same filter, same exposure, same gain,
same sensor: untreated, all those subs fall into a single group, and star registration
fails or silently builds a giant, nearly empty canvas. The pointing (``RA``/``DEC``) is
therefore a group discriminator **for lights alone**, via :func:`detect_panels`. Darks,
biases and flats have no useful pointing — the shutter is closed or the mount is aimed at a
light panel.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field

from ..i18n import translate as _t
from .scan import FrameInfo

#: grouping tolerances, in seconds (2 s for lights, 10 s for darks — a dark is far more
#: tolerant, its signal varies slowly with exposure).
LIGHT_EXPOSURE_TOL = 2.0
DARK_EXPOSURE_TOL = 10.0
#: temperature tolerance, in °C
TEMPERATURE_TOL = 5.0
#: a dark is a "flat-dark" only if its exposure equals that of the flat to within this
FLAT_DARK_TOLERANCE = 0.5
#: beyond this exposure gap, an unscaled dark deserves a warning
DARK_EXPOSURE_WARN = 5.0
#: beyond this ratio, a scaled dark is worth nothing any more (amplified read noise,
#: non-linearities) — better not to subtract a dark at all.
MAX_DARK_SCALE = 4.0

#: angular separation, in **degrees**, beyond which two lights aim at two different
#: **panels** of a mosaic.
#:
#: The value is bracketed by the two scales it must separate, and sits in the middle:
#:
#: * below — the spread of a *single* panel: dithering (a few tens of pixels, i.e. ~1′ at a
#:   Seestar S50's sampling) and re-centering from one night to the next, of the order of a
#:   few arcminutes on a mount that re-solves at every session;
#: * above — the step between two panels: it is one field minus the overlap, and the
#:   smallest field of the family (Seestar S50, ≈ 0.7° × 1.3°) therefore gives a minimum
#:   step of about 0.55° along the short axis.
#:
#: 15′ = 0.25° thus leaves a factor of ~5 of margin on each side. Too large, and we would
#: merge two neighboring panels of a small field; too small, and a mere re-centering would
#: invent panels where there is only one target.
PANEL_SEPARATION = 0.25

#: decimals of a degree kept in order to **sort** the panels (1e-4° = 0.36″). See
#: :func:`detect_panels`: this is what makes the numbering insensitive to computation noise.
POINTING_ROUNDING = 4


def _fmt_exposure(value: float | None) -> str:
    return "xs" if value is None else f"{value:g}s"


def _fmt_temperature(value: float | None) -> str:
    if value is None:
        return "xC"
    return f"{value:.0f}C".replace("-", "m")


@dataclass
class FrameGroup:
    """A batch of interchangeable frames."""

    kind: str
    filter: str | None = None
    exposure: float | None = None
    binning: int = 1
    temperature: float | None = None
    gain: float | None = None
    width: int | None = None
    height: int | None = None
    #: rig identity (``INSTRUME``, ``TELESCOP``…) — see the module header
    extra: dict = field(default_factory=dict)
    #: mosaic panel number, ``0`` when there is none (the common case).
    #: Unlike ``discriminator``, this is not a tie-breaker but an **identity dimension**:
    #: two panels are not integrated together even if nothing else separates them. The two
    #: compound — two rigs × two panels make four groups, all distinctly named.
    panel: int = 0
    #: pointing of the group (center of the panel), in decimal degrees — vector mean of the
    #: pointings of its frames. Filled in for lights alone; this is what a mosaic step needs
    #: in order to place the panels relative to one another.
    ra: float | None = None
    dec: float | None = None
    #: disambiguation suffix, set by :func:`group_frames` **only** if two groups ended up
    #: with the same key. The common case — a single rig — therefore keeps readable keys,
    #: and the ambiguous case cannot overwrite one master with another.
    discriminator: str = ""
    frames: list[FrameInfo] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Stable, readable identifier — serves as a file name and as a step id."""
        parts = [self.kind]
        if self.filter:
            parts.append(str(self.filter))
        if self.kind in ("light", "dark"):
            parts.append(_fmt_exposure(self.exposure))
        parts.append(f"bin{self.binning}")
        if self.gain is not None:
            parts.append(f"g{self.gain:g}")
        parts.append(_fmt_temperature(self.temperature))
        if self.panel:
            parts.append(f"panel{self.panel}")
        if self.discriminator:
            parts.append(self.discriminator)
        return "_".join(parts)

    @property
    def paths(self) -> list[str]:
        return [f.path for f in self.frames]

    @property
    def sections(self) -> tuple[str | None, str | None]:
        """``(BIASSEC, TRIMSEC)`` of the group — sensor-specific, therefore shared."""
        for frame in self.frames:
            if frame.biassec or frame.trimsec:
                return (frame.biassec, frame.trimsec)
        return (None, None)

    @property
    def master(self) -> str | None:
        """Already built master supplied with the batch, if there is one.

        Its presence removes the need to make one: that is the whole point of a master
        library, which we do not want to rebuild at every session. The first one found wins
        — two masters for the same group is an ambiguity the user has to resolve.
        """
        return next((f.path for f in self.frames if f.is_master), None)

    @property
    def geometry(self) -> tuple[int | None, int | None]:
        return (self.width, self.height)

    @property
    def pointing(self) -> tuple[float | None, float | None]:
        """``(RA, Dec)`` of the group center, in degrees — ``(None, None)`` if unknown."""
        return (self.ra, self.dec)

    def __len__(self) -> int:
        return len(self.frames)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "kind": self.kind, "filter": self.filter,
            "exposure": self.exposure, "binning": self.binning,
            "temperature": self.temperature, "gain": self.gain,
            "width": self.width, "height": self.height, "extra": dict(self.extra),
            "panel": self.panel, "ra": self.ra, "dec": self.dec,
            "discriminator": self.discriminator,
            "count": len(self.frames), "frames": [f.to_dict() for f in self.frames],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FrameGroup:
        return cls(
            kind=data["kind"], filter=data.get("filter"), exposure=data.get("exposure"),
            binning=int(data.get("binning", 1)), temperature=data.get("temperature"),
            gain=data.get("gain"), width=data.get("width"), height=data.get("height"),
            extra=dict(data.get("extra") or {}),
            panel=int(data.get("panel") or 0),
            ra=data.get("ra"), dec=data.get("dec"),
            discriminator=data.get("discriminator", ""),
            frames=[FrameInfo.from_dict(f) for f in data.get("frames", [])],
        )

    def __repr__(self) -> str:
        return f"FrameGroup({self.key!r}, {len(self.frames)} frames)"


def _significant_for(kind: str) -> tuple[bool, bool]:
    """(the filter counts, the exposure counts) for this kind of frame."""
    return (kind in ("light", "flat"), kind in ("light", "dark"))


def _close(a: float | None, b: float | None, tol: float) -> bool:
    """Two compatible values — an unknown value is compatible with everything."""
    if a is None or b is None:
        return True
    return abs(a - b) <= tol


def _same_geometry(a: FrameGroup | FrameInfo, b: FrameGroup | FrameInfo) -> bool:
    """Hard criterion — an unknown geometry stays compatible (RAW, missing header)."""
    if a.width is None or b.width is None:
        return True
    return (a.width, a.height) == (b.width, b.height)


def _same_gain(a: FrameGroup | FrameInfo, b: FrameGroup | FrameInfo) -> bool:
    """Hard criterion — an unknown gain stays compatible, for want of anything better."""
    if a.gain is None or b.gain is None:
        return True
    return abs(float(a.gain) - float(b.gain)) < 1e-6


def _same_setup(a: FrameGroup | FrameInfo, b: FrameGroup | FrameInfo) -> bool:
    """Hard criterion on the identity keywords the two have **in common**.

    A frame that does not declare ``TELESCOP`` stays compatible with one that does:
    requiring the keyword to be present would rule out perfectly sound datasets in which
    only part of the frames carry the information.
    """
    common = set(a.extra) & set(b.extra)
    return all(a.extra[name] == b.extra[name] for name in common)


# --- mosaic panels ------------------------------------------------------------------------


def angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Angular separation between two pointings, in degrees (haversine formula).

    Comparing raw right ascensions is the classic mistake: at δ = 80°, 1° of RA is worth
    only 10′ on the sky, and near the pole two subs of the **same** panel appear separated
    by several degrees. The ``cos δ`` factor is indispensable, and the haversine carries it
    while handling the wrap through 0 h — two subs at 359.9° and 0.1° are neighbors.
    """
    phi1, phi2 = math.radians(dec1), math.radians(dec2)
    dphi = phi2 - phi1
    dlambda = math.radians(ra2 - ra1)
    a = (math.sin(dphi / 2.0) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2)
    return math.degrees(2.0 * math.asin(math.sqrt(min(1.0, a))))


def _centroid(points: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    """Mean pointing of a batch, by averaging unit vectors.

    Averaging the RAs arithmetically would give 180° for two subs bracketing 0 h.
    """
    if not points:
        return (None, None)
    x = y = z = 0.0
    for ra, dec in points:
        phi, lam = math.radians(dec), math.radians(ra)
        x += math.cos(phi) * math.cos(lam)
        y += math.cos(phi) * math.sin(lam)
        z += math.sin(phi)
    if abs(x) < 1e-12 and abs(y) < 1e-12 and abs(z) < 1e-12:
        return (None, None)  # diametrically opposite pointings: no center is meaningful
    return (math.degrees(math.atan2(y, x)) % 360.0,
            math.degrees(math.atan2(z, math.hypot(x, y))))


def detect_panels(frames: list[FrameInfo],
                  separation: float = PANEL_SEPARATION) -> dict[str, int]:
    """Panel number (starting at 1) per path, or ``{}`` if there is only one pointing.

    **Single-link** clustering: two subs less than ``separation`` apart belong to the same
    panel, and the relation propagates. It is the right choice here — a panel spreads by
    continuous drift (dithering, re-centering), never by jumps —, and it is independent of
    the order of the frames, hence **deterministic**: two scans of the same folder return
    the same numbers.

    Panels are numbered by increasing (declination, right ascension), and not in discovery
    order: group keys serve as file names, they cannot depend on the order in which the
    disk is walked.

    >>> retina.pipeline.groups.detect_panels(inventory.of_kind("light"))
    {'/data/panel_a_001.fits': 1, ...}
    """
    located: list[tuple[float, float, str]] = [
        (float(f.dec), float(f.ra), f.path)
        for f in frames if f.ra is not None and f.dec is not None]
    if len(located) < 2:
        return {}
    located.sort()

    if _single_pointing(located, separation):
        return {}

    # Single link, sweeping by increasing declination: |Δδ| is a lower bound on the
    # separation, so as soon as it exceeds the threshold the comparisons for this frame can
    # stop.
    parent = list(range(len(located)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (dec_a, ra_a, _) in enumerate(located):
        for j in range(i + 1, len(located)):
            dec_b, ra_b, _ = located[j]
            if dec_b - dec_a > separation:
                break
            if angular_separation(ra_a, dec_a, ra_b, dec_b) <= separation:
                parent[root(j)] = root(i)

    batches: dict[int, list[tuple[float, float, str]]] = {}
    for index, pointing in enumerate(located):
        batches.setdefault(root(index), []).append(pointing)
    if len(batches) < 2:
        return {}

    centers = {key: _centroid([(ra, dec) for dec, ra, _ in members])
               for key, members in batches.items()}

    def rank_of(key: int) -> tuple[float, float]:
        ra, dec = centers[key]
        if ra is None or dec is None:  # degenerate center: the first member is authoritative
            dec, ra = batches[key][0][0], batches[key][0][1]
        # Rounding before comparison: two panels in the same declination band have centers
        # that are equal **to within computation noise** (1e-9), and without this rounding
        # that noise would decide their numbers — hence their file names, from one scan to
        # the next. 1e-4° = 0.36″, three orders of magnitude below the spread of a real panel.
        return (round(dec, POINTING_ROUNDING), round(ra, POINTING_ROUNDING))

    order = sorted(batches, key=rank_of)
    return {path: rank + 1
            for rank, key in enumerate(order) for _, _, path in batches[key]}


def _single_pointing(located: list[tuple[float, float, str]], separation: float) -> bool:
    """True if the spread of the batch **guarantees** a single pointing — the fast exit.

    This is the common case, and it must stay linear: we bound the separation of the
    farthest pair from above by the spread of the batch (haversine applied to the ranges,
    with the largest ``cos δ`` observed, the only one that bounds the right ascension term
    from above). If that bound holds below the threshold, no pair can cross it and comparing
    them is pointless.
    """
    decs = [dec for dec, _, _ in located]
    span_dec = max(decs) - min(decs)
    if span_dec > separation:
        return False
    ras = sorted(ra for _, ra, _ in located)
    # circular range: the full circle minus the largest empty interval
    deviations = [b - a for a, b in itertools.pairwise(ras)]
    deviations.append(360.0 - (ras[-1] - ras[0]))
    span_ra = 360.0 - max(deviations)
    cos_max = max(math.cos(math.radians(d)) for d in decs)
    a = (math.sin(math.radians(span_dec) / 2.0) ** 2
         + cos_max**2 * math.sin(math.radians(span_ra) / 2.0) ** 2)
    return math.degrees(2.0 * math.asin(math.sqrt(min(1.0, a)))) <= separation


def group_frames(frames: list[FrameInfo],
                 light_exposure_tol: float = LIGHT_EXPOSURE_TOL,
                 dark_exposure_tol: float = DARK_EXPOSURE_TOL,
                 temperature_tol: float = TEMPERATURE_TOL,
                 panel_separation: float = PANEL_SEPARATION) -> list[FrameGroup]:
    """Groups frames by type × geometry × binning × filter × exposure × temperature.

    Grouping is greedy: a frame joins the first group compatible within the tolerances, or
    opens a new one. ``unknown`` frames are set aside — classifying them by default would
    manufacture wrong masters — as are those explicitly excluded
    (:func:`retina.pipeline.exclude`).

    The lights of a **mosaic** are additionally split by panel (:func:`detect_panels`):
    without that, a smart telescope's "framing mode" would drown several pointings in a
    single group, which registration could not stack.
    """
    kept_rows = [f for f in frames if f.kind != "unknown" and not f.excluded]
    # Panels are looked for on the lights alone, and before any grouping: angular separation
    # depends on no other criterion, and a panel must carry the same number in every filter
    # for the layers to superimpose.
    panels = detect_panels([f for f in kept_rows if f.kind == "light"], panel_separation)

    groups: list[FrameGroup] = []
    for frame in sorted(kept_rows, key=lambda f: (f.kind, f.filter or "", f.exposure or 0.0,
                                                 f.binning, f.path)):
        by_filter, by_exposure = _significant_for(frame.kind)
        tol = dark_exposure_tol if frame.kind == "dark" else light_exposure_tol
        panel = panels.get(frame.path, 0)
        match = next(
            (g for g in groups
             if g.kind == frame.kind
             and g.panel == panel
             and g.binning == frame.binning
             and _same_geometry(g, frame)
             and _same_gain(g, frame)
             and _same_setup(g, frame)
             and (not by_filter or (g.filter or "").lower() == (frame.filter or "").lower())
             and (not by_exposure or _close(g.exposure, frame.exposure, tol))
             and _close(g.temperature, frame.temperature, temperature_tol)),
            None,
        )
        if match is None:
            match = FrameGroup(
                kind=frame.kind,
                filter=frame.filter if by_filter else None,
                # The exposure is kept even when it is not used for grouping: a group of
                # flats must be able to state its exposure so that a flat-dark can be
                # looked for. It is merely representative, not discriminating.
                exposure=frame.exposure,
                binning=frame.binning,
                temperature=frame.temperature,
                gain=frame.gain,
                width=frame.width,
                height=frame.height,
                extra=dict(frame.extra),
                panel=panel,
            )
            groups.append(match)
        match.frames.append(frame)
        # An unknown value is absorbed by the first known value of the group: the group
        # thereby keeps an identity usable for matching.
        if match.exposure is None:
            match.exposure = frame.exposure
        if match.temperature is None:
            match.temperature = frame.temperature
        if match.gain is None:
            match.gain = frame.gain
        if match.width is None:
            match.width, match.height = frame.width, frame.height
        for name, value in frame.extra.items():
            match.extra.setdefault(name, value)
    for group in groups:
        if group.kind == "light":
            group.ra, group.dec = _centroid(
                [(f.ra, f.dec) for f in group.frames
                 if f.ra is not None and f.dec is not None])
    _disambiguate(groups)
    return groups


def _slug(value: str) -> str:
    """Keyword value reduced to a file name fragment."""
    return re.sub(r"[^A-Za-z0-9]+", "", str(value))[:12] or "x"


def _disambiguate(groups: list[FrameGroup]) -> None:
    """Makes the keys unique when the rig alone distinguishes two groups.

    The key serves as a step identifier **and** as a master file name: two homonymous groups
    would write over each other. We suffix only the groups actually in collision, so as not
    to lengthen the names of the common case — a single rig.
    """
    by_key: dict[str, list[FrameGroup]] = {}
    for group in groups:
        by_key.setdefault(group.key, []).append(group)
    for homonyms in by_key.values():
        if len(homonyms) < 2:
            continue
        # we suffix with the keyword that separates them, failing that with a rank
        names = sorted({name for g in homonyms for name in g.extra})
        distinctive = [name for name in names
                       if len({g.extra.get(name) for g in homonyms}) == len(homonyms)]
        for rank, group in enumerate(homonyms):
            if distinctive:
                group.discriminator = _slug(group.extra.get(distinctive[0], ""))
            else:
                group.discriminator = f"s{rank + 1}"


@dataclass
class CalibrationStep:
    """One operation of a group's calibration chain.

    ``op`` is ``subtract`` or ``divide``, ``role`` says which master supplies it, ``master``
    carries its group key. ``derived`` marks the **dark current** (master dark minus master
    bias), the only intermediate the chain manufactures along the way.
    """

    op: str
    role: str
    master: str
    scale: float = 1.0
    derived: str | None = None

    def to_dict(self) -> dict:
        return {"op": self.op, "role": self.role, "master": self.master,
                "scale": self.scale, "derived": self.derived}


@dataclass
class CalibrationMatch:
    """The masters retained for a group of lights (or of flats)."""

    target: FrameGroup
    bias: FrameGroup | None = None
    dark: FrameGroup | None = None
    flat: FrameGroup | None = None
    #: factor applied to the dark. ≠ 1 ⇒ a "bias + scaled dark current" arrangement.
    dark_scale: float = 1.0
    #: decisions to explain to the user (missing dark, scaling refused…)
    notes: list[str] = field(default_factory=list)

    @property
    def scaled(self) -> bool:
        """True if the dark must be debiased then scaled before subtraction."""
        return abs(self.dark_scale - 1.0) > 1e-6

    @property
    def is_empty(self) -> bool:
        """No master: the group needs no calibration step."""
        return self.bias is None and self.dark is None and self.flat is None

    @property
    def chain(self) -> list[CalibrationStep]:
        """The operations that will be applied, in order.

        This is the ``ImageCalibration`` formula — ``(target − bias − k·dark) / flat`` —
        stated with the masters actually retained. It lives here rather than in the
        interface: which masters enter the chain, and in what order, is an astronomy
        decision, not a rendering one. The GUI only has to draw it.
        """
        steps: list[CalibrationStep] = []
        if self.bias is not None:
            steps.append(CalibrationStep("subtract", "bias", self.bias.key))
        if self.dark is not None:
            steps.append(CalibrationStep(
                "subtract", "dark", self.dark.key, self.dark_scale,
                # Scaling a dark requires first removing its bias, which does not depend on
                # the exposure: it is that dark current which is multiplied.
                derived=self.bias.key if (self.scaled and self.bias is not None) else None))
        if self.flat is not None:
            steps.append(CalibrationStep("divide", "flat", self.flat.key))
        return steps

    def to_dict(self) -> dict:
        return {
            "target": self.target.key,
            "bias": self.bias.key if self.bias else None,
            "dark": self.dark.key if self.dark else None,
            "flat": self.flat.key if self.flat else None,
            "dark_scale": self.dark_scale,
            "chain": [s.to_dict() for s in self.chain],
            "notes": list(self.notes),
        }


def _closest(candidates: list[FrameGroup], target: FrameGroup) -> FrameGroup | None:
    """The closest group in exposure, then in temperature."""
    if not candidates:
        return None

    def distance(group: FrameGroup) -> tuple[float, float]:
        exposure_gap = (0.0 if target.exposure is None or group.exposure is None
                        else abs(group.exposure - target.exposure))
        temperature_gap = (0.0 if target.temperature is None or group.temperature is None
                           else abs(group.temperature - target.temperature))
        return (exposure_gap, temperature_gap)

    return min(candidates, key=distance)


def _compatible(candidates: list[FrameGroup], target: FrameGroup) -> list[FrameGroup]:
    """Candidates passing the hard criteria: same geometry, same binning."""
    return [g for g in candidates
            if g.binning == target.binning
            and _same_geometry(g, target)
            and _same_gain(g, target)
            and _same_setup(g, target)]


def _match_light(light: FrameGroup, biases: list[FrameGroup], darks: list[FrameGroup],
                 flats: list[FrameGroup]) -> CalibrationMatch:
    match = CalibrationMatch(target=light)
    bias = _closest(_compatible(biases, light), light)
    match.dark = _closest(_compatible(darks, light), light)

    if match.dark is None:
        if darks:
            match.notes.append(_t("no compatible dark: lights will not be subtracted"))
        # without a dark, the bias remains the only possible subtraction
        match.bias = bias
    else:
        gap = (abs((match.dark.exposure or 0.0) - (light.exposure or 0.0))
               if light.exposure and match.dark.exposure else 0.0)
        if gap <= 1e-6:
            pass  # exact dark: it already carries the bias, no need to subtract it twice
        elif not light.exposure or not match.dark.exposure:
            match.notes.append(_t("unknown exposure: dark used as is"))
        else:
            scale = light.exposure / match.dark.exposure
            if scale > MAX_DARK_SCALE or scale < 1.0 / MAX_DARK_SCALE:
                match.notes.append(
                    _t("dark {dark} too far from {light} (×{scale:.2f}): dark ignored").format(
                        dark=_fmt_exposure(match.dark.exposure),
                        light=_fmt_exposure(light.exposure), scale=scale))
                match.dark = None
                match.bias = bias
            elif bias is None:
                match.notes.append(
                    _t("dark {dark} not scaled for {light}: no master bias to extract the "
                      "dark current from").format(
                        dark=_fmt_exposure(match.dark.exposure),
                        light=_fmt_exposure(light.exposure)))
            else:
                match.bias = bias
                match.dark_scale = scale
                match.notes.append(
                    _t("dark current scaled ×{scale:.2f} ({dark} → {light})").format(
                        scale=scale, dark=_fmt_exposure(match.dark.exposure),
                        light=_fmt_exposure(light.exposure)))
            if gap > DARK_EXPOSURE_WARN and not match.scaled and match.dark is not None:
                match.notes.append(
                    _t("{gap:g} s exposure gap with the dark, without scaling").format(gap=gap))

    same_filter = [g for g in _compatible(flats, light)
                   if (g.filter or "").lower() == (light.filter or "").lower()]
    if same_filter:
        match.flat = _closest(same_filter, light)
    else:
        neutral = [g for g in _compatible(flats, light) if not g.filter]
        if len(neutral) == 1 and light.filter:
            match.flat = neutral[0]
            match.notes.append(_t("filterless flat used for lack of anything better"))
        elif flats:
            match.notes.append(
                _t("no flat for filter {filter}").format(
                    filter=light.filter or _t("(none)")))
    return match


def _match_flat(flat: FrameGroup, biases: list[FrameGroup],
                darks: list[FrameGroup]) -> CalibrationMatch:
    """Flat-dark if there is one (identical exposure), bias otherwise — never both."""
    match = CalibrationMatch(target=flat)
    flat_darks = [g for g in _compatible(darks, flat)
                  if _close(g.exposure, flat.exposure, FLAT_DARK_TOLERANCE)]
    if flat_darks:
        match.dark = _closest(flat_darks, flat)
        match.notes.append(_t("same-exposure flat-dark: it already carries the bias"))
    else:
        match.bias = _closest(_compatible(biases, flat), flat)
        if match.bias is None and biases:
            match.notes.append(_t("no compatible bias: flats integrated raw"))
    return match


@dataclass
class Survey:
    """The grouping of an inventory **and** the matching that follows from it.

    The two go together: a group of lights without a flat master is not a grouping anomaly,
    it is the result of the matching — and it is nevertheless what has to be shown on the
    group's line. Bringing them together spares the wizard two calls and, above all, spares
    it from recomputing an approximate grouping of its own: the keys it displays are then
    exactly those the plan will use.
    """

    groups: list[FrameGroup] = field(default_factory=list)
    matches: dict[str, CalibrationMatch] = field(default_factory=dict)

    def to_dict(self) -> dict:
        # Groups are serialized whole (frames included): that is what allows sending them
        # back as is to `plan(groups=…)` after correction.
        return {
            "groups": [g.to_dict() for g in self.groups],
            "matches": {k: m.to_dict() for k, m in self.matches.items()},
        }


def survey(inventory, **tolerances) -> Survey:
    """Groups an inventory and matches its masters — the overview before the plan.

    >>> state = retina.pipeline.survey(inventory)
    >>> [(g.key, state.matches[g.key].flat) for g in state.groups if g.kind == "light"]
    """
    batches = group_frames(inventory.frames, **tolerances)
    return Survey(groups=batches, matches=match_calibration(batches))


def match_calibration(groups: list[FrameGroup]) -> dict[str, CalibrationMatch]:
    """Matches each group of **lights and flats** to its masters.

    Dictionary key = :attr:`FrameGroup.key` of the target group.
    """
    biases = [g for g in groups if g.kind == "bias"]
    darks = [g for g in groups if g.kind == "dark"]
    flats = [g for g in groups if g.kind == "flat"]

    matches: dict[str, CalibrationMatch] = {}
    for flat in flats:
        matches[flat.key] = _match_flat(flat, biases, darks)
    for light in (g for g in groups if g.kind == "light"):
        matches[light.key] = _match_light(light, biases, darks, flats)
    return matches
