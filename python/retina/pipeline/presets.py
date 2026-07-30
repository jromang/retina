"""Pre-processing presets — the settings that change from one rig to the next.

A preset does **not** describe a chain of steps (that is the job of
:mod:`retina.pipeline.plan`): it says which ones to enable and with what parameters. It is
serializable, hence editable in the wizard, saveable, and transportable over RPC.

Four presets are supplied:

``auto``
    Everything is deduced from the inventory: debayering if the lights carry a Bayer matrix,
    expected filters = those found. It is the default, and it is right almost always.
``osc``
    One-shot color sensor: debayering forced.
``mono_lrgb`` / ``mono_sho``
    Monochrome sensor with a filter wheel. They differ only by the **expected** filters: the
    plan emits a note if one of them fails to show up, which catches the classic mistake
    (incomplete folder, filter misnamed in the headers) before three hours of computation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..i18n import N_
from ..i18n import translate as _t


@dataclass
class Preset:
    """Settings of a pre-processing run. All values are JSON-serializable."""

    name: str = "auto"
    #: debayering: ``None`` = decided by the presence of a Bayer matrix
    debayer: bool | None = None
    #: correct the bias drift through the overscan and remove the unexposed area, when the
    #: header declares them (``BIASSEC``/``TRIMSEC``). Enabled by default: without a
    #: declared section the step does not arise, and when it does arise it corrects a
    #: systematic error measured at 20 % of the sky background.
    overscan: bool = True
    #: cosmetic correction (hot/cold pixels) after calibration
    cosmetic: bool = True
    #: **LPS** — removal of the column/row pattern (CMOS banding), between the cosmetic
    #: correction and the debayer. False by default: not every sensor suffers from it, and
    #: correcting a pattern that does not exist costs nothing but brings nothing either.
    #: To be enabled when `LinearDefectDetection` finds some on a calibrated sub.
    lps: bool = False
    lps_columns: bool = True
    lps_rows: bool = False
    #: thresholds of the cosmetic correction, in sigmas
    hot_sigma: float = 3.0
    cold_sigma: float = 3.0
    #: pass the master biases through Superbias (multiscale model of the bias) — a
    #: specialist's tool, hence disabled by default: on few frames it also smooths the
    #: useful signal
    superbias: bool = False
    #: search for the dark scale factor instead of deducing it from the exposure ratio.
    #: Expensive (a score of subtractions per frame) and pointless when the dark has the
    #: right exposure, hence reserved for the case where it really has to be scaled.
    dark_optimization: bool = True
    #: measure the frames (FWHM, noise, stars) in order to weight and choose the reference
    measure: bool = True
    #: weight the integration by the measurements
    weighting: bool = True
    #: Python frame approval expression (empty = all approved).
    #: E.g.: ``eccentricity < 0.6 and fwhm_n > 0.2``
    approval: str = ""
    #: Python weighting expression (empty = SubframeSelector's default formula)
    weighting_expression: str = ""
    #: star registration
    register: bool = True
    #: local normalization before integration
    normalize: bool = True
    #: background scale for LocalNormalization, in pixels
    normalization_scale: float = 128.0
    #: reconstruct by **drizzle** instead of stacking the registered frames. Requires real
    #: sub-pixel dithering between subs; without it drizzle brings nothing and costs a lot.
    #: Classic registration is then short-circuited — drizzle registers by itself, from the
    #: calibrated, non-interpolated frames, failing which there would be nothing left to
    #: reconstruct.
    drizzle: bool = False
    drizzle_scale: int = 2
    drizzle_pixfrac: float = 0.9
    #: crop the incomplete edges of the integrated image. Enabled by default, as is usual:
    #: after registration the edges receive only a fraction of the subs, and those values
    #: skew the automatic stretch as much as the statistics.
    autocrop: bool = True
    #: astrometrically solve the final images and write the WCS into their header.
    #: Established practice enables it by default; we do not, and the reason is material:
    #: PixInsight embeds its star catalog, where our offline solver downloads its index
    #: files on first call — several hundred MB that we do not trigger behind the user's
    #: back. A solving failure never interrupts the batch.
    platesolve: bool = False
    #: minimum weight, as a fraction of the best of the batch: below this threshold the
    #: frame is set aside. The usual value — a sub twenty times worse than the best brings
    #: nothing and degrades the rejection.
    min_weight: float = 0.05
    #: sigma rejection thresholds at the integration of the lights
    sigma_low: float = 4.0
    sigma_high: float = 3.0
    #: expected filters — empty = those of the inventory; otherwise a note flags the missing
    expected_filters: tuple[str, ...] = ()
    #: **output pedestal** of the light calibration, like the usual `lightOutputPedestal`:
    #: subtracting the dark can yield negative pixels, which clipping to zero would turn
    #: into a silent bias on the sky background. ``auto`` doses it on the distribution;
    #: ``manual`` uses ``pedestal``. Flats and darks do not need one — they are positive by
    #: construction.
    pedestal_mode: str = "auto"
    pedestal: float = 0.0
    #: grouping tolerances (``None`` = the constants in ``groups.py``). A smart telescope
    #: with an unregulated sensor requires ignoring the temperature, failing which each sub
    #: would form its own group of darks.
    light_exposure_tol: float | None = None
    dark_exposure_tol: float | None = None
    temperature_tol: float | None = None
    #: extract Ha and OIII from a color sensor behind a dual-band filter, instead of
    #: debayering into RGB. Produces two mono integrations per group.
    dual_band: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["expected_filters"] = list(self.expected_filters)
        return data

    def tolerances(self) -> dict[str, float]:
        """Tolerances to pass to ``group_frames``/``survey`` — only those actually set.

        The absent ones leave the module constants in place: a preset must not have to
        repeat values it does not change.
        """
        names = ("light_exposure_tol", "dark_exposure_tol", "temperature_tol")
        return {name: getattr(self, name) for name in names if getattr(self, name) is not None}

    @classmethod
    def from_dict(cls, data: dict) -> Preset:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if "expected_filters" in known:
            known["expected_filters"] = tuple(known["expected_filters"])
        return cls(**known)


PRESETS: dict[str, Preset] = {
    "auto": Preset(name="auto"),
    "osc": Preset(name="osc", debayer=True),
    "mono_lrgb": Preset(name="mono_lrgb", debayer=False,
                        expected_filters=("L", "R", "G", "B")),
    "mono_sho": Preset(name="mono_sho", debayer=False,
                       expected_filters=("Ha", "SII", "OIII")),
    # Smart telescopes: color sensor, **unregulated** sensor (hence the wide-open temperature
    # tolerance: splitting by temperature would make one group of darks per sub), and short
    # subs in very large numbers. Plate-solving stays disabled as everywhere else, so as not
    # to trigger the index download behind the user's back.
    "seestar": Preset(name="seestar", debayer=True, temperature_tol=100.0),
    "dwarf": Preset(name="dwarf", debayer=True, temperature_tol=100.0),
}

#: interface labels, held here so the wizard does not have to hard-code them. Marked with
#: ``N_`` and translated on read (``describe_presets``): they are written at module import,
#: before the language of the session is known.
_LABELS = {
    "auto": (N_("Automatic"), N_("Deduced from the contents of the folder")),
    "osc": (N_("Colour (OSC)"), N_("One-shot colour sensor, debayering forced")),
    "mono_lrgb": (N_("Mono LRGB"), N_("L/R/G/B filter wheel")),
    "mono_sho": (N_("Mono SHO"), N_("Ha/SII/OIII narrowband")),
    "seestar": (N_("Seestar"), N_("ZWO Seestar — short subs, unregulated sensor")),
    "dwarf": (N_("Dwarf"), N_("DwarfLab Dwarf — short subs, unregulated sensor")),
}


def resolve(preset: str | Preset | dict | None) -> Preset:
    """Accepts a name, a :class:`Preset`, a serialized dict, or nothing (→ ``auto``)."""
    if preset is None:
        return PRESETS["auto"]
    if isinstance(preset, Preset):
        return preset
    if isinstance(preset, dict):
        return Preset.from_dict(preset)
    known = PRESETS.get(preset)
    if known is None:
        raise ValueError(_t("Unknown preset: {preset!r} (known: {known})").format(
            preset=preset, known=sorted(PRESETS)))
    # copy: a named preset must not be modified by a caller that adjusts it
    return Preset.from_dict(known.to_dict())


def describe_presets() -> list[dict]:
    """``[{name, label, hint}]`` — enough to fill a selector without coding the labels."""
    return [{"name": name, "label": _t(_LABELS[name][0]), "hint": _t(_LABELS[name][1])}
            for name in PRESETS]
