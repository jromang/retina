"""Which processes deliberately have no figure, and why.

A gap in a catalogue of 141 pages is invisible unless someone writes it down. Without this
file, "no figure for `Integration`" and "nobody has got to `Integration` yet" look exactly the
same six months from now — and ``tests/test_docs.py`` turns the distinction into an assertion:
every registered process is either illustrated by a module in this folder **or** named here
with a reason. A new process therefore cannot arrive figureless in silence.

Three kinds of reason appear below, and only the first two are permanent:

- **nothing to photograph** — the process yields measurements, metadata, a catalogue query or
  a configuration change, and touches no pixel. A before/after would be two identical frames.
- **no data** — a figure is meaningful but the repository has nothing honest to make it from,
  and fabricating the scene would illustrate the algorithm on a toy. This is where the
  narrowband and photometric-calibration families sit, and where they will stay until a
  licensed multi-filter dataset joins ``resources/samples.json``.
- **pending** — illustrable with what is already here, simply not written yet. These are work
  items, not decisions.
"""

from __future__ import annotations

NOT_ILLUSTRATED: dict[str, str] = {
    # --- nothing to photograph: measurements, metadata, queries, configuration ---------- #
    "APASSCatalog": "queries a catalogue and returns rows; touches no pixel",
    "AperturePhotometry": "measures fluxes into `.result`; the image is unchanged",
    "Blink": "steps through frames in the viewport; a still cannot show it",
    "ConeSearch": "queries SIMBAD and returns objects; touches no pixel",
    "DynamicPSF": "fits stars and reports parameters; the image is unchanged",
    "EphemerisGenerator": "computes ephemerides into `.result`; touches no pixel",
    "FITSHeader": "reads and edits header keywords, never the data",
    "FWHMEccentricity": "draws a viewport overlay and measures; the pixels stay as they were",
    "GaiaCatalog": "queries Gaia and returns rows; touches no pixel",
    "ImageIdentifier": "renames a view; nothing to photograph",
    "LightCurve": "produces a photometric time series, which is a plot and not an image",
    "LinearDefectDetection": "reports the defective columns it finds; the correction is "
                             "`LinearPatternSubtraction`",
    "MosaicPlanner": "computes panel centres into `.result` and a CSV",
    "NoiseEvaluation": "measures the noise level into `.result`",
    "PlateSolve": "attaches a WCS; the pixels are untouched, and what it enables is shown by "
                  "`Annotation` and `SurveyReference`",
    "RadialProfileMeasurement": "measures a profile, which is a plot and not an image",
    "SEPSourceExtraction": "returns a source list; the image is unchanged",
    "SourceExtraction": "returns a source list; the image is unchanged",
    "Statistics": "reports statistics; touches no pixel",
    "SubframeSelector": "scores frames and reports; the frames themselves are unchanged",
    "NewImage": "creates a blank frame — a picture of nothing is not a figure",
    "Script": "runs arbitrary user code; there is no one result to show",
    "FilterManager": "manages the filter-curve database; a configuration process",
    "ColorManagementSetup": "sets colour-management preferences; a configuration process",
    "RGBWorkingSpace": "sets the working-space coefficients; no visible change on its own",
    "AssignICCProfile": "tags the data with a profile without converting it — by definition "
                        "the pixels do not move",

    # --- no honest data in the repository ---------------------------------------------- #
    "AIDenoise": "needs a trained ONNX model, and none ships (see TODO_REFERENCE2 lot 1.2)",
    "AIDeconvolution": "needs a trained ONNX model, and none ships",
    "StarRemoval": "needs a trained ONNX model, and none ships",
    "B3Estimator": "needs a co-registered continuum/narrowband pair, which the repository "
                   "does not carry",
    "NBRGBCombination": "needs co-registered broadband and narrowband frames of one field",
    "NarrowbandNormalization": "needs co-registered narrowband channels of one field",
    "PhotometricColorCalibration": "needs a solved field whose stars have catalogue "
                                   "magnitudes; the survey composite has no photometry",
    "SpectrophotometricColorCalibration": "same as `PhotometricColorCalibration`, plus Gaia "
                                          "XP spectra for the field",
    "SpectrophotometricFluxCalibration": "same again; needs catalogue fluxes for the field",
    "ICCProfileTransformation": "a profile conversion is a few thousandths of a level on "
                                "screen — real, and below what a WebP figure can show",

    # --- pending: illustrable with what is here, simply not written yet ----------------- #
    "CloneStamp": "pending — needs a source patch and a target chosen by hand",
    "CometAlignment": "pending — needs several frames with a moving target",
    "DefectMap": "pending — needs a defect map file alongside the frame",
    "DrizzleIntegration": "pending — needs several dithered frames",
    "DynamicAlignment": "pending — needs two frames and a pair of matched points",
    "FastIntegration": "pending — needs several frames",
    "FeatureAlignment": "pending — needs two overlapping frames",
    "GalaxyModel": "pending — its isophote fit was numerically unstable on every composite "
                   "tried, which is worth a look before a figure",
    "GradientHDRComposition": "pending — needs several exposures of one field",
    "HDRComposition": "pending — needs several exposures of one field",
    "Inpaint": "pending — needs a mask file alongside the frame",
    "LocalNormalization": "pending — needs two frames of one field at different levels",
    "MosaicReproject": "pending — needs two solved, overlapping frames",
    "PhaseCorrelationAlignment": "pending — needs two shifted frames",
    "Rescale": "pending — needs a frame that does not already span the full range",
    "SeamlessClone": "pending — needs a patch and a target chosen by hand",
    "StarAlignment": "pending — needs two frames of one field; the sample dataset has them",
}
