---
id: _guides/first-light
title: From the stack to the picture
brief: What to do with the image the pipeline just produced — crop, gradient, colour, sharpen, stretch, export.
order: 20
icon: sparkles
keywords: [workflow, stretch, gradient, colour calibration, deconvolution, export, linear]
related: [DynamicCrop, MultiscaleGradientCorrection, SpectrophotometricColorCalibration, GeneralizedHyperbolicStretch, StarRemoval]
---

## Where this starts

You have run the pre-processing and opened its result: one file under
`retina_pipeline/integrated/`, per filter. That image is **linear** — the pixels are still
proportional to the light that fell on the sensor — and pre-processing is only half the road.
What follows is the other half, and it is where the picture appears.

Everything here is a process you can also run from the console; every click writes its Python
line. Nothing in this guide is a shortcut the interface has and a script does not.

## The order, and why it is that order

Work stays **linear** as long as possible. A stretch is a non-linear function: once applied, a
gradient is no longer a gradient, star colours are no longer proportional to flux, and the
noise is no longer uniform — so the tools that assume linearity have to come first. This is the
order every published workflow converges on, whatever the software:

1. **Crop** the registration edges — `DynamicCrop`
2. **Remove the gradient** — `MultiscaleGradientCorrection` or `BackgroundExtraction`
3. **Calibrate the colour** — `PlateSolve` then `SpectrophotometricColorCalibration`
4. **Sharpen and denoise** — `Deconvolution`, `NoiseReduction`
5. **Stretch** — `GeneralizedHyperbolicStretch` or `HistogramTransformation`
6. **Finish** — saturation, curves, star size
7. **Export**

The first four are linear-domain steps; steps 5 onwards are not, and there is no going back
past that line. Which is why one stretches *late*.

## 0. See what you have

A linear image displayed as it is looks black: an average sky background sits around 0.001,
and your screen has 256 levels. Press the **Auto** button of the *Screen stretch* panel (or run
`app.compute_auto_stf()`).

This changes **nothing** in the pixels. It is a display transform — that is the whole point:
you can look at faint nebulosity while the tools keep working on the real values. Opening a
pipeline result from the report does this for you.

> **The distinction to hold on to** — the screen stretch is how you *look*; a stretch process
> is what you *do*. Keep them separate until step 5.

## 1. Crop the edges

Registration shifts every frame onto a common reference, so the borders of a stack are covered
by fewer subs than the centre — sometimes by none. Those edges are noisier, and they will
poison every measurement that follows: a gradient model fitted through a black corner, a
background estimate, an automatic stretch.

Use `retina-doc://DynamicCrop`, drag the frame over the good area, and apply. Do it **first**:
everything downstream measures the image, and it should measure the image you are keeping.

## 2. Remove the gradient

Light pollution, moonlight and twilight leave a slow ramp across the field. It is not part of
the object, and every later step behaves better without it.

- `retina-doc://MultiscaleGradientCorrection` fits the large scales of your image against a
  reference and subtracts the difference. Its reference can come from a survey: run
  `retina-doc://SurveyReference` first — it queries an all-sky survey on your plate solution
  and opens the result as an ordinary window, which you can look at before using it.
- `retina-doc://BackgroundExtraction` and `retina-doc://DynamicBackgroundExtraction` model the
  background from the image itself — automatically, or from samples you place by clicking.
  Prefer them on a field where the object fills the frame and no survey helps.

Judge the result on the **background**, not on the object: a correction that flattens the sky
and dims the galaxy has taken signal with it.

## 3. Calibrate the colour

This is the step that makes colour mean something rather than look plausible.

1. `retina-doc://PlateSolve` — the astrometric solution. Colour calibration needs to know which
   stars it is looking at.
2. `retina-doc://SpectrophotometricColorCalibration` — it measures the flux of catalogue stars
   in each channel, compares it with their **spectra** from Gaia, and derives the gains that
   make your channels agree with physics. Pick your filters and your sensor from the
   drop-downs: 54 curves are bundled, and naming the right ones is what separates a real
   calibration from a plausible one.
3. Under narrowband filters, tick **Narrowband mode** and give the wavelength and width of each
   channel instead.

`retina-doc://BackgroundNeutralization` beforehand puts the sky background at neutral, which is
the reference the rest is measured against.

## 4. Sharpen and denoise — still linear

`retina-doc://Deconvolution` undoes part of the blur imposed by the atmosphere and the optics.
It works on linear data and nowhere else: the point-spread function it inverts is a
*convolution*, and a stretch is not one. Measure the PSF from the stars themselves
(`retina-doc://DynamicPSF` shares its fitter) rather than guessing a Gaussian width.

`retina-doc://NoiseReduction` and `retina-doc://TGVDenoise` smooth the background. Work under a
mask so the object keeps its detail — see below.

If you have an ONNX model installed, `retina-doc://AIDeconvolution` and
`retina-doc://AIDenoise` do the same job with a network; the model name, version and SHA-256
go into the history and into the FITS keywords, so the result stays reproducible.

## 5. Stretch — the crossing

Now the image becomes a picture.

- `retina-doc://GeneralizedHyperbolicStretch` is the one to learn. It gives independent control
  of *how much* to stretch, *where* on the tonal range, and how much to protect the shadows —
  which is what makes it possible to lift nebulosity without flooding the background. Its
  panel draws the curve and the resulting histogram live.
- `retina-doc://HistogramTransformation` is the direct route: three values, black point,
  midtones, white point. The *Apply* button of the screen-stretch panel bakes the auto-stretch
  you have been looking at into the pixels through this very process — one history entry,
  undoable.
- `retina-doc://MaskedStretch` and `retina-doc://ArcsinhStretch` preserve star colour better on
  bright fields.

Watch the black point. Clipping the background to zero is irreversible, and it takes the faint
outer halo of the object with it.

## 6. Finish

- **Masks.** Almost every finishing step wants one: sharpen the object without the background,
  denoise the background without the object. Run `retina-doc://StarMask`,
  `retina-doc://RangeSelection` or `retina-doc://ColorMask` — each opens its result as a window,
  and offers to set it as the mask of the view it came from. The status bar then shows the
  mask, lets you invert it, and change how it is drawn.
- **Colour** — `retina-doc://ColorSaturation`, `retina-doc://CurvesTransformation`, and
  `retina-doc://SCNR` for the green cast that one-shot-colour sensors leave on nebulae.
- **Stars** — `retina-doc://StarRemoval` separates the starless image; process the two apart
  and recombine, or use `retina-doc://StarReduction` directly to shrink them.
- **Narrowband** — `retina-doc://NBRGBCombination` and
  `retina-doc://NarrowbandNormalization` for SHO and HOO palettes.

## 7. Export

**File ▸ Save as**. What to write depends on what for:

| For | Format |
|---|---|
| Archiving, reopening here or in another astro suite | **XISF** — float, keywords, WCS, compressed |
| Editing elsewhere (Photoshop, GIMP, Affinity) | **TIFF** — 32-bit float, no loss |
| Sharing, posting, sending | **PNG** or **JPEG** |

The last row comes with a warning, and it is worth understanding rather than clicking through.
PNG and JPEG store 8 bits per channel. If your image is still linear — because you have been
looking at it through the screen stretch — then what you see and what is in the pixels are two
different things, and the file will be nearly black. Retina asks which you meant: apply the
screen stretch to the exported copy, or write the data unchanged. Apply it, unless you know
you want the linear data.

## Replaying all of it

Everything you have just done is in the view's history, and the history is a recipe. The
history panel's **Recipe from history** button turns it into a `ProcessContainer` you can drop
onto another image — the OIII stack, next month's session on the same object. `app.recipe()`
gives you the same thing as Python.

That is the real reason each step is a serializable process rather than a button: the second
image costs a fraction of the first.

## Where to go next

- `retina-doc://_guides/getting-started` — if you have not read it: the console, the echo, and
  pre-processing a folder.
- The process catalogue, by category, on the documentation home page.
- `retina-doc://PixelMath` — arithmetic on images, as a Python expression.
