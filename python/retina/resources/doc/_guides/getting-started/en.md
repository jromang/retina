---
id: _guides/getting-started
title: First steps
brief: A guided tour of Retina — open an image, stretch it, read the Python echo, then pre-process a whole folder of raw frames.
order: 10
icon: list-check
keywords: [getting started, tour, console, echo, stretch, pre-processing, sample data]
related: [HistogramTransformation, BackgroundExtraction, Integration, SubframeSelector, PixelMath]
---

## What Retina is, in one paragraph

Retina is an astrophotography image processor whose **core is Python**. The window you are
looking at is not the application — it is one *client* of it. The console is another. Both
call the exact same functions, which is why nothing here is reserved for the interface: every
menu entry, every button, every drag of a process icon can be typed instead. This guide walks
through that in about fifteen minutes.

If you would rather have data to try this on before reading further, the **Home** tab offers a
free sample dataset (a real night at Palomar: bias, darks, flats and science frames, 162 MB).
From the console it is one line:

```python
app.download_sample("example-cryo-lfc")
```

## 1. Open your first image

**File → Open**, or the *Your first image…* button on the Home tab. FITS, XISF, TIFF, PNG,
JPEG and camera RAW files all open.

Watch the console while you do it. It prints:

```python
app.open('/data/M31/light_001.fits')
```

That is not a log line — it is the call that just ran. Copy it into a script and it will do
the same thing tomorrow, headless, without this window.

The image arrives **linear**: nearly black, with a few stars. That is correct. A camera
records a signal that spans four orders of magnitude, and your screen shows two. Nothing is
wrong with the file; it simply has not been stretched yet.

## 2. Make it visible — two very different gestures

There are two ways to brighten an image, and confusing them is the classic beginner's mistake.

**The screen transfer function (STF)** changes the *display* only. The pixels are untouched,
nothing enters the history, and any process you run still sees the linear data — which is
what background extraction, calibration and star detection need. Press the auto-stretch
button in the viewport toolbar, or:

```python
app.compute_auto_stf()
```

**A stretch process** rewrites the pixels. That is a real, undoable step in the view's
history, and it is what you do once the linear work is finished:

```python
retina.HistogramTransformation(shadows=0.002, midtones=0.15).execute_on(app.active_view)
app.undo()          # …and back, if you disagree
```

Rule of thumb for the whole session: **stay linear as long as possible**. Calibrate, remove
the gradient, integrate — then stretch. See `retina-doc://HistogramTransformation` for the
transfer function itself, and `retina-doc://GeneralizedHyperbolicStretch` for the modern
alternative.

## 3. The console, and why every click writes in it

Open the console (**View → Console**, or the panel of the same name). It is a full IPython
shell running *inside* the application, with two names already bound:

- `app` — the application: windows, views, the active selection, history, layout, preferences;
- `retina` — the package: every process class, the I/O layer, the pre-processing pipeline.

Try it on the image you just opened:

```python
view = app.active_view
view.image.median(), view.image.mad()     # robust statistics
app.apply(retina.GaussianConvolution(sigma=2.0))
app.undo()
```

Now do something with the mouse — move a slider in a process panel, create a preview, change
the zoom. Each gesture prints its Python equivalent. This is the fastest way to learn the API:
you do not read it, you *watch* it being written. It is also where recipes come from — select
the lines that worked, save them as a script, and replay them on the next target.

Tab completion, `?` for help and `??` for source all work, because it really is IPython.

## 4. Pre-process a folder of raw frames

This is the part that usually takes an evening in other software. Point Retina at the folder
that holds your session — lights, darks, flats, bias, in whatever arrangement of subfolders
your capture software produced — and it works out the rest.

From the interface: the **Pre-processing** panel (*Get started → Pre-process a folder of raw
frames…* on the Home tab). From the console, the same three steps, which are also what the
panel calls:

```python
inventory = retina.pipeline.scan("/data/M31")
print(inventory.counts())                 # what was found, and how it was classified

plan = retina.pipeline.plan(inventory, preset="auto")
print(plan.describe())                    # what will run — inspect BEFORE launching

report = retina.pipeline.run(plan)
print(report.describe())
```

Three things worth knowing before you launch:

- **The plan is inspectable and editable.** `plan.describe()` prints every step in order.
  Nothing is decided at run time that you could not read beforehand — a plan replayed gives
  the same result.
- **Everything is written to disk**, under `<folder>/retina_pipeline/` (`masters/`,
  `calibrated/`, `registered/`, `integrated/`). A hundred 50-megapixel frames do not fit in
  memory, an interrupted run resumes for free, and every intermediate can be opened here.
- **Frames are measured, then judged.** `SubframeSelector` fits an elliptical PSF on the stars
  of each light to get FWHM, eccentricity and signal weight. Rejecting six frames out of a
  hundred re-runs the integration only — the measurements are cached per file.

Two verbs that look alike and are not: `retina.pipeline.exclude(...)` takes a file out of the
project entirely (wrong target, corrupt, wrong type), while `retina.pipeline.set_rejects(...)`
keeps calibrating and registering a frame but gives it zero weight in the stack. The first
invalidates the calibration cache; the second does not.

## 5. Where to go next

- **The process catalogue** — the Documentation home page lists every process by
  category, and counts them for you. Each page states what the process does, its parameters and their defaults.
- **The natural order of a session**: `retina-doc://ImageCalibration` →
  `retina-doc://StarAlignment` → `retina-doc://Integration` → `retina-doc://BackgroundExtraction`
  → `retina-doc://PhotometricColorCalibration` → stretch → `retina-doc://NoiseReduction`.
- **`retina-doc://PixelMath`** if you like doing arithmetic on your images: the expression is
  plain Python evaluated on numpy arrays, so the whole scientific stack is available inside it.
- **Scripts** — the script editor runs a file against the live session, and
  `retina-doc://Script` turns that run into a single undoable history step.
- **`python -m retina.run recipe.py`** runs the same script with no window at all, on a
  machine with no display. That is the real test of the promise: if it works in the console,
  it works headless.
