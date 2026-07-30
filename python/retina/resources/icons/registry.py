"""Registry of process icons — ``process_id → icon name`` mapping.

The SVGs live in ``resources/icons/lib/<name>.svg`` (a subset of the **Tabler Icons**
set, MIT licence, monochrome ``currentColor`` strokes → they take the theme colour).

Resolution (see :func:`retina.doc.icon_name`):
1. the ``icon:`` of the doc frontmatter (explicit override), otherwise
2. :data:`PROCESS_ICONS` (per process), otherwise
3. :data:`CATEGORY_ICONS` (fallback per category), otherwise
4. :data:`DEFAULT_ICON`.

Adding a process = one line here (or an ``icon:`` in its doc). No dedicated SVG required.
"""

from __future__ import annotations

DEFAULT_ICON = "wand"

# Fallback per category (covers every process not listed individually).
CATEGORY_ICONS: dict[str, str] = {
    "Astrometry": "telescope",
    "BackgroundModelization": "layers-subtract",
    "Calibration": "adjustments",
    "ColorCalibration": "palette",
    "ColorManagement": "color-swatch",
    "ColorSpaces": "color-swatch",
    "Convolution": "focus-2",
    "CosmeticCorrection": "bandage",
    "LinearPatternSubtraction": "line",
    "Debayer": "grid-dots",
    "Deconvolution": "focus-centered",
    "Fourier": "wave-sine",
    "Geometry": "crop",
    "Global": "database",
    "Image": "photo",
    "ImageInspection": "zoom-scan",
    "ImageIntegration": "stack-2",
    "ImageRegistration": "target",
    "IntensityTransformations": "chart-histogram",
    "MaskGeneration": "ghost",
    "Morphology": "shape",
    "MultiscaleProcessing": "stack",
    "NoiseGeneration": "grain",
    "NoiseReduction": "sparkles",
    "Painting": "brush",
    "PixelMath": "math-function",
}

# Per-process overrides (finer visual identity). Optional.
PROCESS_ICONS: dict[str, str] = {
    # Astrometry
    "PlateSolve": "map-pin",
    "Annotation": "tag",
    "CatalogAnnotation": "list-details",
    "EphemerisGenerator": "calendar-stats",
    # BackgroundModelization
    "BackgroundExtraction": "layers-subtract",
    "DynamicBackgroundExtraction": "layers-subtract",
    "GradientCorrection": "chart-line",
    "MultiscaleGradientCorrection": "stack",
    "GradientMergeMosaic": "grid-4x4",
    "RollingBallBackground": "circle",
    "SEPBackground": "layers-subtract",
    # Calibration
    "ImageCalibration": "adjustments",
    "LocalNormalization": "adjustments-horizontal",
    "Superbias": "photo",
    "MergeCFA": "grid-dots",
    "SplitCFA": "grid-dots",
    # ColorCalibration
    "B3Estimator": "database",
    "BackgroundNeutralization": "color-swatch",
    "ColorCalibration": "palette",
    "NBRGBCombination": "color-swatch",
    "NarrowbandNormalization": "adjustments",
    "ComponentSeparation": "arrows-split",
    "HistogramMatching": "chart-histogram",
    "LinearFit": "chart-line",
    "FilterManager": "adjustments-horizontal",
    "PhotometricColorCalibration": "palette",
    "SCNR": "color-swatch",
    "SpectrophotometricColorCalibration": "palette",
    "SpectrophotometricFluxCalibration": "prism",
    # ColorManagement
    "AssignICCProfile": "certificate",
    "ColorManagementSetup": "settings",
    "ICCProfileTransformation": "transform",
    # ColorSpaces
    "ChannelExtraction": "layers-linked",
    "ChannelCombination": "layers-linked",
    "ConvertToGrayscale": "contrast",
    "ConvertToRGBColor": "palette",
    "LRGBCombination": "layers-linked",
    "RGBWorkingSpace": "color-swatch",
    # Convolution
    "Convolution": "focus-2",
    "GaussianConvolution": "focus-2",
    "LarsonSekanina": "windmill",
    "UnsharpMask": "focus-centered",
    # CosmeticCorrection
    "CosmeticCorrection": "bandage",
    "CosmicClip": "bolt",
    "DefectMap": "grid-pattern",
    "PixelInterpolation": "grid-dots",
    # Debayer
    "Debayer": "grid-dots",
    # Deconvolution
    "AIDeconvolution": "sparkles",
    "Deconvolution": "focus-centered",
    "RestorationFilter": "wand",
    # Fourier
    "FourierTransform": "wave-sine",
    "InverseFourierTransform": "wave-sine",
    # Geometry
    "AutoCrop": "crop",
    "Overscan": "crop",
    "Crop": "crop",
    "DynamicCrop": "crop",
    "FastRotation": "rotate-clockwise",
    "IntegerResample": "grid-4x4",
    "Resample": "arrows-maximize",
    "Rotation": "rotate",
    # Global (catalogues)
    "APASSCatalog": "database",
    "GaiaCatalog": "database",
    # Image
    "FITSHeader": "file-info",
    "ImageIdentifier": "id",
    "NewImage": "photo",
    "SampleFormatConversion": "transform",
    "Statistics": "chart-dots",
    # ImageInspection
    "Blink": "eye",
    "AberrationInspector": "grid-4x4",
    "AperturePhotometry": "circle",
    "FWHMEccentricity": "grid-dots",
    "LinearDefectDetection": "line",
    "NoiseEvaluation": "wave-sine",
    "DynamicPSF": "chart-dots-3",
    "RadialProfileMeasurement": "chart-arcs",
    "SEPSourceExtraction": "scan",
    "SourceExtraction": "scan",
    "SubframeSelector": "list-check",
    # ImageIntegration
    "DrizzleIntegration": "droplet",
    "FastIntegration": "stack-2",
    "GradientHDRComposition": "stack",
    "HDRComposition": "stack",
    "Integration": "stack-2",
    "MosaicReproject": "grid-4x4",
    # ImageRegistration
    "CometAlignment": "comet",
    "DynamicAlignment": "target",
    "FeatureAlignment": "target",
    "PhaseCorrelationAlignment": "target",
    "StarAlignment": "stars",
    # IntensityTransformations
    "AdaptiveStretch": "adjustments",
    "ArcsinhStretch": "wave-sine",
    "GeneralizedHyperbolicStretch": "chart-arcs",
    "AutoHistogram": "chart-bar",
    "Binarize": "binary",
    "ColorSaturation": "color-swatch",
    "CurvesTransformation": "chart-line",
    "ExponentialTransformation": "math-function",
    "HistogramTransformation": "chart-histogram",
    "MaskedStretch": "ghost",
    "Rescale": "arrows-maximize",
    # MaskGeneration
    "RangeSelection": "select",
    "SatelliteTrailDetection": "line",
    "StarMask": "star",
    "ColorMask": "color-swatch",
    "StarReduction": "star",
    "StarRemoval": "star-off",
    # Morphology
    "MorphologicalTransformation": "shape",
    # MultiscaleProcessing
    "GalaxyModel": "atom",
    "GradientHDRCompression": "stack",
    "HDRMultiscaleTransform": "stack",
    "LocalHistogramEqualization": "chart-histogram",
    "MultiscaleAdaptiveStretch": "stack",
    "MultiscaleLinearTransform": "stack",
    "MultiscaleMedianTransform": "stack",
    "RickerWaveletEnhance": "wave-sine",
    "WaveletTransform": "wave-sine",
    # NoiseGeneration
    "NoiseGenerator": "grain",
    "SimplexNoise": "grain",
    # NoiseReduction
    "AIDenoise": "wand",
    "ACDNR": "sparkles",
    "FastNLMeansDenoise": "sparkles",
    "NoiseReduction": "sparkles",
    "NonLocalMeansDenoise": "sparkles",
    "TGVDenoise": "sparkles",
    "WaveletDenoise": "wave-sine",
    # Painting
    "CloneStamp": "rubber-stamp",
    "Inpaint": "eraser",
    "SeamlessClone": "copy",
    # PixelMath
    "Invert": "contrast",
    "PixelMath": "math-function",
}


def resolve(process_id: str, category: str = "", override: str = "") -> str:
    """Effective icon name for a process (see the resolution rule at the top)."""
    return (
        override
        or PROCESS_ICONS.get(process_id)
        or CATEGORY_ICONS.get(category)
        or DEFAULT_ICON
    )


def referenced_names() -> set[str]:
    """The set of icon names actually used (for vendoring/tests)."""
    return {DEFAULT_ICON, *CATEGORY_ICONS.values(), *PROCESS_ICONS.values()}
