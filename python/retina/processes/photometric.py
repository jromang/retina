"""PhotometricColorCalibration — photometric white balance through Gaia (≈ SPCC).

Principle: we measure the instrumental flux of the stars in R/G/B (aperture photometry at the
Gaia positions projected by the WCS), we compare it to the catalog fluxes derived from the
Gaia magnitudes (RP↔R, G↔G, BP↔B), and we derive per-channel gains that make the stellar
colors conform to Gaia.

Assumed approximation: Gaia BP/G/RP ≈ broad B/G/R bands (a full spectrophotometric
calibration uses the filter+sensor response curves and synthetic spectra). Requires a WCS
(PlateSolve) and a **color** image.
"""

from __future__ import annotations

import re

import numpy as np

from ..i18n import N_
from ..i18n import translate as _t
from ..process.base import Parameter, Process
from ..process.registry import register


@register
class PhotometricColorCalibration(Process):
    process_id = "PhotometricColorCalibration"
    category = "ColorCalibration"
    supports_realtime = False  # catalog query
    parameters = [
        Parameter("mag_bright", "real", 7.0, -5.0, 20.0,
                  label=N_("Bright magnitude (avoid saturation)")),
        Parameter("mag_faint", "real", 13.0, 0.0, 22.0, label=N_("Faint magnitude")),
        Parameter("aperture_radius", "real", 5.0, 1.0, 50.0, label=N_("Aperture radius (px)")),
        Parameter("max_stars", "int", 300, 3, 5000, label=N_("Max stars")),
        Parameter("apply", "bool", True, label=N_("Apply (otherwise: measure only)")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._catalog = None  # (ra, dec, bp, g, rp) list supplied explicitly
        self.gains = None
        self.n_stars = 0

    def set_catalog(self, objects) -> PhotometricColorCalibration:
        self._catalog = list(objects)
        return self

    def _query_gaia(self, win):
        from astroquery.gaia import Gaia

        h, w = win.main_view.image.data.shape[:2]
        center = win.wcs.pixel_to_world(w / 2, h / 2)
        radius = min(center.separation(win.wcs.pixel_to_world(0, 0)).deg, 2.0)
        query = (
            f"SELECT TOP {int(self.max_stars)} ra, dec, "
            f"phot_bp_mean_mag, phot_g_mean_mag, phot_rp_mean_mag "
            f"FROM gaiadr3.gaia_source "
            f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {center.ra.deg}, {center.dec.deg}, {radius})) "
            f"AND phot_g_mean_mag BETWEEN {self.mag_bright} AND {self.mag_faint} "
            f"AND phot_bp_mean_mag IS NOT NULL AND phot_rp_mean_mag IS NOT NULL"
        )
        rows = Gaia.launch_job_async(query).get_results()
        return [
            (float(r["ra"]), float(r["dec"]), float(r["phot_bp_mean_mag"]),
             float(r["phot_g_mean_mag"]), float(r["phot_rp_mean_mag"]))
            for r in rows
        ]

    def _compute_gains(self, view):
        from astropy.stats import sigma_clipped_stats
        from photutils.aperture import CircularAperture, aperture_photometry

        win = view.window
        if win is None or win.wcs is None:
            raise ValueError(
                _t("PhotometricColorCalibration requires a WCS (run PlateSolve first)."))
        data = view.image.data
        if data.shape[2] < 3:
            raise ValueError(_t("PhotometricColorCalibration requires a color (RGB) image."))

        cat = self._catalog if self._catalog is not None else self._query_gaia(win)
        h, w = data.shape[:2]
        r = float(self.aperture_radius)
        ras = np.array([o[0] for o in cat])
        decs = np.array([o[1] for o in cat])
        xs, ys = win.wcs.world_to_pixel_values(ras, decs)
        inb = (xs >= r) & (xs < w - r) & (ys >= r) & (ys < h - r)
        if inb.sum() < 3:
            raise ValueError(
                _t("PhotometricColorCalibration: too few catalog stars in the field.")
            )

        positions = list(zip(xs[inb], ys[inb], strict=True))
        cat_in = [cat[i] for i in np.where(inb)[0]]
        aps = CircularAperture(positions, r=r)

        meas = np.zeros((len(positions), 3), dtype=np.float64)
        for c in range(3):
            _, med, _ = sigma_clipped_stats(data[:, :, c], sigma=3.0)
            phot = aperture_photometry(data[:, :, c].astype(np.float64) - med, aps)
            meas[:, c] = np.asarray(phot["aperture_sum"])

        # catalog flux per channel: R←RP, G←G, B←BP
        cat_flux = np.array([[10 ** (-0.4 * o[4]), 10 ** (-0.4 * o[3]), 10 ** (-0.4 * o[2])]
                             for o in cat_in])
        valid = (meas > 0).all(axis=1) & np.isfinite(cat_flux).all(axis=1)
        if valid.sum() < 3:
            raise ValueError(_t("PhotometricColorCalibration: too few measurable stars."))

        ratios = cat_flux[valid] / meas[valid]
        gains = np.median(ratios, axis=0)
        gains = gains / gains[1]  # G channel = reference (white balance)
        self.gains = gains
        self.n_stars = int(valid.sum())
        return gains

    def execute_on(self, view) -> bool:
        gains = self._compute_gains(view)
        if not self.apply:
            return True  # measure only: no history entry
        data = view.image.data
        out = data.copy()
        for c in range(3):
            out[:, :, c] = data[:, :, c] * gains[c]
        out = np.clip(out, 0.0, 1.0).astype(np.float32)
        view.begin_process(self.process_id, process=self)
        view.set_image(view.image.with_data(out))
        view.end_process()
        return True

    def execute_on_image(self, image):
        raise NotImplementedError(
            _t("PhotometricColorCalibration requires a view (WCS): execute_on(view).")
        )


# --- shared helpers (SPCC / flux calibration) ----------------------------------
def _gaia_query(win, mag_bright, mag_faint, max_stars):
    from astroquery.gaia import Gaia

    h, w = win.main_view.image.data.shape[:2]
    center = win.wcs.pixel_to_world(w / 2, h / 2)
    radius = min(center.separation(win.wcs.pixel_to_world(0, 0)).deg, 2.0)
    query = (
        f"SELECT TOP {int(max_stars)} ra, dec, "
        f"phot_bp_mean_mag, phot_g_mean_mag, phot_rp_mean_mag "
        f"FROM gaiadr3.gaia_source "
        f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {center.ra.deg}, {center.dec.deg}, {radius})) "
        f"AND phot_g_mean_mag BETWEEN {mag_bright} AND {mag_faint} "
        f"AND phot_bp_mean_mag IS NOT NULL AND phot_rp_mean_mag IS NOT NULL"
    )
    rows = Gaia.launch_job_async(query).get_results()
    return [
        (float(r["ra"]), float(r["dec"]), float(r["phot_bp_mean_mag"]),
         float(r["phot_g_mean_mag"]), float(r["phot_rp_mean_mag"]))
        for r in rows
    ]


def _measure_catalog_flux(view, cat, radius, channels):
    """Aperture photometry at the catalog positions projected by the WCS.

    Returns ``(meas [N, channels], cat_in)`` for the stars falling inside the field.
    """
    from astropy.stats import sigma_clipped_stats
    from photutils.aperture import CircularAperture, aperture_photometry

    win = view.window
    if win is None or win.wcs is None:
        raise ValueError(_t("WCS required (run PlateSolve first)."))
    data = view.image.data
    h, w = data.shape[:2]
    r = float(radius)
    # An entry is either a ``(ra, dec, …)`` tuple or a dict — SPCC carries spectra, which a
    # positional tuple cannot describe.
    ras = np.array([o["ra"] if isinstance(o, dict) else o[0] for o in cat])
    decs = np.array([o["dec"] if isinstance(o, dict) else o[1] for o in cat])
    xs, ys = win.wcs.world_to_pixel_values(ras, decs)
    inb = (xs >= r) & (xs < w - r) & (ys >= r) & (ys < h - r)
    if inb.sum() < 3:
        raise ValueError(_t("Too few catalog stars in the field."))
    positions = list(zip(xs[inb], ys[inb], strict=True))
    cat_in = [cat[i] for i in np.where(inb)[0]]
    aps = CircularAperture(positions, r=r)
    meas = np.zeros((len(positions), len(channels)), dtype=np.float64)
    for k, c in enumerate(channels):
        _, med, _ = sigma_clipped_stats(data[:, :, c], sigma=3.0)
        phot = aperture_photometry(data[:, :, c].astype(np.float64) - med, aps)
        meas[:, k] = np.asarray(phot["aperture_sum"])
    return meas, cat_in


#: wavelength grid of the synthetic photometry, in nanometers. It is the one of the Gaia DR3
#: sampled spectra (336–1020 nm, 2 nm step): taking it finer would bring nothing since the
#: spectra do not exist anywhere else.
SPECTRAL_GRID = np.arange(336.0, 1021.0, 2.0)


def _gaia_query_xp(win, mag_bright, mag_faint, max_stars) -> list[dict]:
    """Stars of the field **with their sampled spectrum** (Gaia DR3 XP).

    Two queries: the cone first, then the spectra through ``DataLink``. A star with no XP
    spectrum is kept with ``spectrum=None`` — it will go back through the BP/G/RP photometric
    path, which is better than discarding it.
    """
    from astroquery.gaia import Gaia

    h, w = win.main_view.image.data.shape[:2]
    center = win.wcs.pixel_to_world(w / 2, h / 2)
    radius = min(center.separation(win.wcs.pixel_to_world(0, 0)).deg, 2.0)
    request = (
        f"SELECT TOP {int(max_stars)} source_id, ra, dec, "
        f"phot_bp_mean_mag, phot_g_mean_mag, phot_rp_mean_mag, has_xp_sampled "
        f"FROM gaiadr3.gaia_source "
        f"WHERE 1=CONTAINS(POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {center.ra.deg}, {center.dec.deg}, {radius})) "
        f"AND phot_g_mean_mag BETWEEN {mag_bright} AND {mag_faint} "
        f"AND phot_bp_mean_mag IS NOT NULL AND phot_rp_mean_mag IS NOT NULL"
    )
    lines = Gaia.launch_job_async(request).get_results()
    stars = [
        {"ra": float(r["ra"]), "dec": float(r["dec"]), "bp": float(r["phot_bp_mean_mag"]),
         "g": float(r["phot_g_mean_mag"]), "rp": float(r["phot_rp_mean_mag"]),
         "source_id": int(r["source_id"]), "spectrum": None,
         "has_xp": bool(r["has_xp_sampled"])}
        for r in lines
    ]
    avec_xp = [e["source_id"] for e in stars if e["has_xp"]]
    if not avec_xp:
        return stars

    batches = Gaia.load_data(ids=avec_xp, retrieval_type="XP_SAMPLED",
                          data_release="Gaia DR3", format="votable")
    spectres: dict[int, np.ndarray] = {}
    for key, tables in batches.items():
        # The source identifier is in the **key** ("XP_SAMPLED-Gaia DR3 <id>.xml"), not in the
        # table metadata: `meta['source_id']` is absent there. Checked against the real
        # service — relying on it silently discarded every spectrum.
        chiffres = re.findall(r"\d{6,}", str(key))
        if not chiffres:
            continue
        sid = int(chiffres[-1])
        for table in (tables if isinstance(tables, list) else [tables]):
            convertir = getattr(table, "to_table", None)
            t = convertir() if convertir is not None else table
            try:
                lam = np.asarray(t["wavelength"], dtype=np.float64)   # nm
                flux = np.asarray(t["flux"], dtype=np.float64)
            except (KeyError, TypeError, ValueError):
                continue
            spectres[sid] = np.interp(SPECTRAL_GRID, lam, flux, left=0.0, right=0.0)
    for star in stars:
        star["spectrum"] = spectres.get(star["source_id"])
    return stars


@register
class SpectrophotometricColorCalibration(Process):
    """SPCC — white balance by **synthetic photometry** on real spectra.

    The principle: for each star of the field we know what the instrument *should have*
    measured — the star's spectrum integrated over each channel's response (filter
    transmission × sensor efficiency) — and we compare it to what it did measure. The ratio
    gives each channel's gain. The white reference then fixes what we declare to be neutral.

    That is what distinguishes SPCC from PCC, which makes do with an RP→R / G→G / BP→B
    mapping. It still takes real spectra and real curves: the **Gaia DR3 sampled spectra**
    (``spectrum_source='gaia_xp'``) and the :mod:`retina.spectra` database supply them.
    Without network access, ``set_catalog`` injects both.

    The **narrowband mode** replaces the filter curves by rectangular passbands described by
    their wavelength and their width — more accurate than a scanned curve for a 3 or 7 nm
    filter, and it is what the SHO crowd uses.
    """

    process_id = "SpectrophotometricColorCalibration"
    category = "ColorCalibration"
    supports_realtime = False  # catalog query
    #: spectrum-less fallback: nominal passbands on the (RP, G, BP) fluxes, rows summing to 1
    _PASSBANDS = np.array([
        [0.85, 0.10, 0.05],   # R ← mostly RP
        [0.10, 0.80, 0.10],   # G ← mostly G
        [0.05, 0.10, 0.85],   # B ← mostly BP
    ])
    parameters = [
        Parameter("mag_bright", "real", 7.0, -5.0, 20.0, label=N_("Bright magnitude")),
        Parameter("mag_faint", "real", 13.0, 0.0, 22.0, label=N_("Faint magnitude")),
        Parameter("aperture_radius", "real", 5.0, 1.0, 50.0, label=N_("Aperture radius (px)")),
        Parameter("max_stars", "int", 300, 3, 5000, label=N_("Max stars")),
        Parameter("apply", "bool", True, label=N_("Apply (otherwise: measure only)")),
        # --- instrumental response ---
        Parameter("spectrum_source", "enum", "gaia_xp",
                  choices=("gaia_xp", "gaia_photometry"), label=N_("Spectrum source")),
        Parameter("red_filter", "str", "", label=N_("Red filter")),
        Parameter("green_filter", "str", "", label=N_("Green filter")),
        Parameter("blue_filter", "str", "", label=N_("Blue filter")),
        Parameter("red_sensor", "str", "", label=N_("Red sensor QE")),
        Parameter("green_sensor", "str", "", label=N_("Green sensor QE")),
        Parameter("blue_sensor", "str", "", label=N_("Blue sensor QE")),
        Parameter("white_reference", "str", "average_spiral_galaxy",
                  label=N_("White reference")),
        # --- narrowband ---
        Parameter("narrowband", "bool", False, label=N_("Narrowband mode")),
        Parameter("red_wavelength", "real", 656.3, 300.0, 1100.0,
                  label=N_("Red wavelength (nm)")),
        Parameter("red_bandwidth", "real", 7.0, 0.1, 300.0, label=N_("Red bandwidth (nm)")),
        Parameter("green_wavelength", "real", 500.7, 300.0, 1100.0,
                  label=N_("Green wavelength (nm)")),
        Parameter("green_bandwidth", "real", 7.0, 0.1, 300.0,
                  label=N_("Green bandwidth (nm)")),
        Parameter("blue_wavelength", "real", 500.7, 300.0, 1100.0,
                  label=N_("Blue wavelength (nm)")),
        Parameter("blue_bandwidth", "real", 7.0, 0.1, 300.0, label=N_("Blue bandwidth (nm)")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._catalog = None
        self.gains = None
        self.n_stars = 0
        self.n_spectra = 0

    def set_catalog(self, objects) -> SpectrophotometricColorCalibration:
        """Injects a catalog without network access.

        Accepts the old ``(ra, dec, bp, g, rp)`` form and the new one, a dict carrying in
        addition ``spectrum``: the spectrum array sampled on :data:`SPECTRAL_GRID`.
        """
        self._catalog = list(objects)
        return self

    # --- instrumental response ------------------------------------------------
    def has_response(self) -> bool:
        """Do we know what the instrument's response looks like?

        As long as no curve is named, the three channels would have the **same** response
        (transmission 1 everywhere): integrating a spectrum over them would return the same
        number three times, and SPCC would become a silent no-op — the worst of behaviors. In
        that case we explicitly fall back on the nominal passbands, that is, on the behavior
        that predates spectral response support. Naming a filter or a sensor is enough to
        switch over.
        """
        return bool(self.narrowband or self.red_filter or self.green_filter
                    or self.blue_filter or self.red_sensor or self.green_sensor
                    or self.blue_sensor)

    def responses(self) -> np.ndarray:
        """Response ``(3, len(SPECTRAL_GRID))`` of the R, G, B channels."""
        from .. import spectra

        if self.narrowband:
            return np.stack([
                spectra.boxcar_response(self.red_wavelength, self.red_bandwidth, SPECTRAL_GRID),
                spectra.boxcar_response(self.green_wavelength, self.green_bandwidth,
                                        SPECTRAL_GRID),
                spectra.boxcar_response(self.blue_wavelength, self.blue_bandwidth,
                                        SPECTRAL_GRID),
            ])
        paires = ((self.red_filter, self.red_sensor), (self.green_filter, self.green_sensor),
                  (self.blue_filter, self.blue_sensor))
        return np.stack([spectra.channel_response(f, s, SPECTRAL_GRID) for f, s in paires])

    def _white(self, responses: np.ndarray) -> np.ndarray:
        """What the white reference would give in each channel.

        Dividing the gains by these three numbers is what *defines* white: without it we would
        calibrate against a flat spectrum, which is nobody's white.
        """
        from .. import spectra

        if not self.white_reference or not self.has_response():
            return np.ones(3)
        curve = spectra.resample(
            spectra.load_curve(self.white_reference, "white_reference"), SPECTRAL_GRID)
        blanc = responses @ curve
        if not np.all(blanc > 0):
            raise ValueError(
                _t("SPCC: white reference {ref!r} does not cover the requested bands — "
                   "check the narrowband mode wavelengths.").format(ref=self.white_reference))
        return blanc

    # --- synthetic fluxes -----------------------------------------------------
    @staticmethod
    def _entry(obj) -> dict:
        """Normalizes a catalog entry, old form included."""
        if isinstance(obj, dict):
            return obj
        ra, dec, bp, g, rp = obj[:5]
        return {"ra": ra, "dec": dec, "bp": bp, "g": g, "rp": rp, "spectrum": None}

    def _synthetic(self, entries: list[dict], responses: np.ndarray) -> np.ndarray:
        """Fluxes ``(N, 3)`` the instrument would have measured on each star."""
        synth = np.zeros((len(entries), 3), dtype=np.float64)
        avec_spectre = 0
        for i, e in enumerate(entries):
            spectrum = e.get("spectrum")
            if (spectrum is not None and self.spectrum_source == "gaia_xp"
                    and self.has_response()):
                synth[i] = responses @ np.asarray(spectrum, dtype=np.float64)
                avec_spectre += 1
            else:
                # Fallback: three photometric points and nominal passbands. Less accurate —
                # the star's reddening and metallicity are gone — but a star without an XP
                # spectrum is better than a star discarded.
                flux = np.array([10 ** (-0.4 * e["rp"]), 10 ** (-0.4 * e["g"]),
                                 10 ** (-0.4 * e["bp"])])
                synth[i] = self._PASSBANDS @ flux
        self.n_spectra = avec_spectre
        return synth

    def _compute_gains(self, view):
        if view.image.data.shape[2] < 3:
            raise ValueError(_t("SPCC requires a color (RGB) image."))
        win = view.window
        if self._catalog is not None:
            raw_data = self._catalog
        elif self.spectrum_source == "gaia_xp":
            raw_data = _gaia_query_xp(win, self.mag_bright, self.mag_faint, self.max_stars)
        else:
            raw_data = _gaia_query(win, self.mag_bright, self.mag_faint, self.max_stars)
        entries = [self._entry(o) for o in raw_data]
        meas, kept_rows = _measure_catalog_flux(view, entries, self.aperture_radius, (0, 1, 2))

        responses = self.responses()
        synth = self._synthetic(kept_rows, responses)
        valid = (meas > 0).all(axis=1) & (synth > 0).all(axis=1) & np.isfinite(synth).all(axis=1)
        if valid.sum() < 3:
            raise ValueError(_t("SPCC: too few measurable stars."))
        gains = np.median(synth[valid] / meas[valid], axis=0) / self._white(responses)
        gains = gains / gains[1]  # G = reference
        self.gains = gains
        self.n_stars = int(valid.sum())
        return gains

    def execute_on(self, view) -> bool:
        gains = self._compute_gains(view)
        if not self.apply:
            return True
        data = view.image.data
        out = data.copy()
        for c in range(3):
            out[:, :, c] = data[:, :, c] * gains[c]
        out = np.clip(out, 0.0, 1.0).astype(np.float32)
        view.begin_process(self.process_id, process=self)
        view.set_image(view.image.with_data(out))
        view.end_process()
        return True

    def execute_on_image(self, image):
        raise NotImplementedError(_t("SPCC requires a view (WCS): execute_on(view)."))


@register
class SpectrophotometricFluxCalibration(Process):
    """Flux calibration: derives an instrument→physical zero point from Gaia (G magnitude).

    Measures the instrumental flux (luminance) of the catalog stars and compares it to the
    physical flux derived from their G magnitude → a common scale factor (``zero_point``). In
    ``apply`` mode, the image is brought back to that scale. Useful for photometry and for
    intensity measurements comparable across sessions. WCS required.
    """

    process_id = "SpectrophotometricFluxCalibration"
    category = "ColorCalibration"
    supports_realtime = False  # catalog query
    parameters = [
        Parameter("mag_bright", "real", 7.0, -5.0, 20.0, label=N_("Bright magnitude")),
        Parameter("mag_faint", "real", 13.0, 0.0, 22.0, label=N_("Faint magnitude")),
        Parameter("aperture_radius", "real", 5.0, 1.0, 50.0, label=N_("Aperture radius (px)")),
        Parameter("max_stars", "int", 300, 3, 5000, label=N_("Max stars")),
        Parameter("apply", "bool", False, label=N_("Apply the scale (otherwise: measure)")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._catalog = None
        self.zero_point = None
        self.n_stars = 0

    def set_catalog(self, objects) -> SpectrophotometricFluxCalibration:
        self._catalog = list(objects)
        return self

    def _compute(self, view):
        win = view.window
        cat = self._catalog if self._catalog is not None else _gaia_query(
            win, self.mag_bright, self.mag_faint, self.max_stars)
        data = view.image.data
        lum_channel = 1 if data.shape[2] >= 3 else 0  # G in color, otherwise the single channel
        meas, cat_in = _measure_catalog_flux(view, cat, self.aperture_radius, (lum_channel,))
        meas = meas[:, 0]
        phys = np.array([10 ** (-0.4 * o[3]) for o in cat_in])  # physical flux ∝ 10^(-0.4 G)
        valid = (meas > 0) & np.isfinite(phys)
        if valid.sum() < 3:
            raise ValueError(_t("Flux calibration: too few measurable stars."))
        self.zero_point = float(np.median(phys[valid] / meas[valid]))
        self.n_stars = int(valid.sum())
        return self.zero_point

    def execute_on(self, view) -> bool:
        zp = self._compute(view)
        if not self.apply:
            return True
        # rescale, normalizing by the max so as to stay in a displayable [0,1]
        data = view.image.data
        scaled = data * zp
        hi = float(scaled.max()) or 1.0
        out = np.clip(scaled / hi, 0.0, 1.0).astype(np.float32)
        view.begin_process(self.process_id, process=self)
        view.set_image(view.image.with_data(out))
        view.end_process()
        return True

    def execute_on_image(self, image):
        raise NotImplementedError(_t("Flux calibration requires a view (WCS): execute_on(view)."))


@register
class FilterManager(Process):
    """Inspects, adds and removes spectral curves — filters, sensors, whites.

    The scriptable counterpart of the :mod:`retina.spectra` database. The built-in curves are
    read-only; the user's live under ``config_dir()/spectra/`` and **shadow** the built-in
    namesake, which makes it possible to correct a curve one believes to be wrong without
    touching the installation.

    The result of the last run is in ``.result`` — this is a measurement process, it
    transforms no image.
    """

    process_id = "FilterManager"
    category = "ColorCalibration"
    is_global = True
    supports_realtime = False
    parameters = [
        Parameter("action", "enum", "list", choices=("list", "show", "add", "remove"),
                  label=N_("Action")),
        Parameter("kind", "enum", "filter",
                  choices=("filter", "sensor", "white_reference"), label=N_("Curve family")),
        Parameter("name", "str", "", label=N_("Curve identifier")),
        Parameter("label", "str", "", label=N_("Display name")),
        Parameter("channel", "str", "", label=N_("Channel")),
        # A curve is a sequence of (wavelength, value) pairs: the flat list is the form the
        # rest of the domain already uses for points (cf. DynamicPSF).
        Parameter("points", "floatlist", [], label=N_("Points (wavelength, value, ...)")),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.result: dict | None = None

    @staticmethod
    def _couples(flat) -> list[tuple[float, float]]:
        values = [float(v) for v in (flat or [])]
        return list(zip(values[0::2], values[1::2], strict=False))

    def execute_global(self, app) -> bool:
        from .. import spectra

        action, kind = self.action, self.kind
        if action == "list":
            self.result = {
                "kind": kind,
                "curves": [
                    {"id": c.id, "name": c.name, "channel": c.channel,
                     "manufacturer": c.manufacturer, "user": c.user, "license": c.license}
                    for c in spectra.list_curves(kind)
                ],
            }
        elif action == "show":
            info = spectra.curve_info(self.name, kind)
            curve = spectra.load_curve(self.name, kind)
            self.result = {
                "id": info.id, "name": info.name, "channel": info.channel,
                "manufacturer": info.manufacturer, "source": info.source,
                "license": info.license, "user": info.user,
                "wavelength_nm": curve[:, 0].tolist(), "value": curve[:, 1].tolist(),
            }
        elif action == "add":
            if not self.name:
                raise ValueError(_t("FilterManager(action='add'): parameter 'name' required."))
            path = spectra.save_user_curve(
                self.name, kind, self._couples(self.points),
                label=self.label, channel=self.channel)
            self.result = {"id": self.name, "kind": kind, "path": str(path)}
        else:
            if not spectra.delete_user_curve(self.name, kind):
                raise ValueError(
                    _t("FilterManager: no user curve {name!r} of kind {kind} "
                       "(built-in curves cannot be removed).").format(name=self.name, kind=kind))
            self.result = {"id": self.name, "kind": kind, "removed": True}
        return True
