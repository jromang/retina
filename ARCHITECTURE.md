# Retina — Architecture

This document is the engineering reference for Retina. It describes what the codebase is,
the four principles that govern it, and — where a decision is not obvious — the failure that
motivated it. Read it before making a structural change; a fair number of the rules here were
paid for once already.

---

## 1. What Retina is

Retina is an open-source astrophotography image-processing application. Its core is a headless
Python domain (`Image`, `View`, `ImageWindow`, `Process`) accelerated by compiled Rust operators
and, where it pays, by CuPy on the GPU. On top of that core sits a workbench user interface —
docking panels, a command palette, a Monaco editor, a WebGL2 viewport — served by a local
aiohttp server and displayed in a native window. The interface is a *client* of the Python API,
with no privileges of its own: everything it can do, a script can do. Retina ships 141 processes,
an end-to-end automated pre-processing pipeline, a project format that round-trips a whole
session including undo history, and an MCP server that exposes the live session to an AI agent.

Licence: GPL-3.0-or-later. Python 3.11+.

---

## 2. The four non-negotiables

1. **Python is the core layer, not a binding bolted on afterwards.** The GUI and user scripts
   manipulate *exactly* the same objects. Scripting is therefore native and free rather than a
   thin veneer maintained in parallel with a compiled core.

2. **Console completeness — everything is reachable from the embedded Python console.** Absolute
   rule: **no feature is reachable only from the GUI.** Open and save, create a window or a
   preview, select the active view, apply a process, manage masks and history, arrange the docks,
   run a batch — all of it goes through the `retina` API exposed in the console. See § 4.

3. **A professional workbench.** Docking, a command centre, a GPU viewport. The interface is
   expected to hold up under a real session, not to demonstrate a concept.

4. **Reproducibility.** Every operation is a serializable, replayable `ProcessInstance`.
   Recipes, per-view history and undo all fall out of that single representation.

### Two corollaries

**No home-grown language.** The application is Python-first, so we do not write a proprietary
DSL or expression parser. `PixelMath` is a **Python expression** evaluated over numpy in a
sandbox (`asteval`, `processes/pixelmath.py`): the whole scientific standard library is available
for free, and the syntax is the one the console already uses.

**Do not reinvent.** `astropy`, `ccdproc`, `photutils`, `astroalign`, `scikit-image` and `scipy`
already cover a large part of the algorithmic surface; processes wrap them rather than
reimplement them. Rust targets only the hot spots identified by profiling
(`scripts/profile_hotspots.py`) — not everything.

---

## 3. The three layers

```
┌───────────────────────────────────────────────────────────────┐
│ Web shell: native window (tao + wry) → TS frontend + WebGL2   │  web/ + crates/retina_shell/
│            ← aiohttp JSON-RPC server                          │  python/retina/server/
│  — a CLIENT of the API, on the same footing as the console    │
├───────────────────────────────────────────────────────────────┤
│  Python core / domain  =  the scripting API                   │  python/retina/{model,process,io}/
│  Image · View · ImageWindow · Preview · STF · History         │
│  Process/ProcessInstance · Parameter · registry (plugins)     │
├───────────────────────────────────────────────────────────────┤
│  Compiled operators (Rust/PyO3, releases the GIL) + GPU       │  crates/retina_core/
└───────────────────────────────────────────────────────────────┘
```

The domain never imports the shell. `import retina` must pull in neither aiohttp nor IPython —
`tests/server/test_headless_parity.py` enforces it.

| Layer | Choice |
|---|---|
| Shell | native window `crates/retina_shell` (tao + wry) loading the server's URL |
| Server | **aiohttp** — one port for HTTP + WebSocket, JSON-RPC 2.0, loopback only |
| Frontend | **Vite + strict TypeScript + Preact/@preact/signals**, source in `web/` |
| Docking | **dockview-core** (two instances: centre and right zone) |
| Image viewport | **WebGL2** — float16 texture, **analytic** STF in the shader (no LUT) |
| Process panels | forms **auto-generated** from `Process.parameters` |
| Script console | embedded IPython `InteractiveShell`, in-process, + **Monaco** editor |
| Icons | codicons for the chrome, Tabler (`/api/icons/`) for the processes |
| Core / domain / API | **Python** + **numpy** (the exchange format) |
| Compiled operators | **Rust + PyO3 + maturin** (crate `retina_core` → `retina._core`) |
| GPU | backend dispatch **numpy (CPU) / CuPy (CUDA)** |
| Formats | `astropy.io.fits` (FITS + WCS), the `xisf` library, `rawpy` (camera RAW) |
| Project / workspace | one `.retina` file = HDF5 (JSON manifest + chunked, compressed arrays) |
| Packaging | **maturin** (wheel), **briefcase** (application bundle) |

---

## 4. Console/GUI parity — the golden rule

The GUI is a **client** of the scriptable API and has **no power of its own**. The engineering
consequences are not optional:

- **Single source of truth.** A GUI action (button, menu item, dragged process icon) **calls the
  same API function** the console offers. An operation is never implemented "in the button
  handler": the handler delegates to `retina.*`. An action with no API equivalent is an
  architectural bug, not a shortcut.

- **A root namespace in the console.** The `app` object plus the `retina` package reach
  everything: `app.open(path)`, `app.windows`, `app.active_view`, `app.new_preview(...)`,
  `SomeProcess(...).execute_on(view)`, `app.layout.*`, `app.run(recipe)`.

- **Python echo.** Every GUI action **emits the equivalent Python code into the console** —
  executable, copyable. The user learns the API by clicking, and can replay or script any
  gesture. The echo is also the source of *recipes* (`ProcessContainer`). The domain publishes it
  through a single hook, `Application.on_echo`; the domain knows nothing about who listens.

- **Headless first.** `import retina` works with no shell: open images, apply processes, save —
  in pure script or CLI (`python -m retina.run recipe.py`), on a machine with no display.

- **Parity tests.** `tests/test_console_parity.py` and `tests/test_workflow_api.py` check that
  features are reachable from the console alone; `web/tests/menus.test.ts` checks that no menu
  entry exists without its API counterpart. No change adds a GUI capability without the
  corresponding API.

There is exactly one documented exception, and it is not a domain action: **window chrome**
(move, resize, minimize, close) and the **system locale** travel over the native IPC channel and
have deliberately no `app.*` equivalent. Moving an OS window is not something a script has any
reason to ask for. The rationale is written out at the top of `crates/retina_shell/src/main.rs`.

---

## 5. The object model

The core of the design. Everything else is arranged around it.

| Type | File | What it is |
|---|---|---|
| `Image` | `model/image.py` | numpy `(H, W, C)` float32 pixel container + robust statistics |
| `View` | `model/view.py` | the addressable target of a process; carries STF and history |
| `ImageWindow` | `model/window.py` | main view + previews + mask + FITS keywords + WCS + viewport |
| `Preview` | `model/window.py` | a named sub-region that **is** a `View` |
| `Process` | `process/base.py` | a schema of typed `Parameter` descriptors; a configured instance **is** the `ProcessInstance` |
| `STF` | `model/stf.py` | non-destructive display transform |
| `ProcessContainer` | `process/container.py` | an ordered, replayable recipe |

**`Image`** holds data normally in `[0, 1]` (the linear astronomical convention), though nothing
enforces it. Geometry, pixel access (`samples`, `sample()`/`set_sample()`), **robust statistics**
(`median`, `mad`, `sn`, `qn`, `bwmv`, `noise_k_sigma`…) and operations (`convolve`, `fft`,
`multiscale_transform`, `resample`, `rescale`, `compute_auto_stretch`).

**`View`** is a main view *or* a preview, same interface: `id`, `image`, `window`, `stf`
(read/write), `properties` (typed metadata), and the linear history. Every process brackets its
edit with `view.begin_process()` / `view.end_process()`, which pushes a `HistoryEntry`. That entry
carries the image, **the process instance that produced it**, and **the mask in force at execution
time**. The last field was added after the fact: without it, replaying an entry later applied the
*current* mask, giving a different result with nothing to say so. Both extra fields have defaults,
so a project written before the change still reads back.

**`Preview`** being a full `View` means any process runs identically on a preview and on a main
view. Previews are **volatile** by default: on each new process the preview restarts from its base
(the corresponding region of the *current* main view), so re-applying automatically undoes the
previous attempt and the tune → apply → look loop never needs an Undo. `store()` freezes a preview
into a standalone object with cumulative history.

**`Process`** instances serialize as Python source (`to_python_source()`, which feeds the echo and
recipes) and as XML. Four entry points: `execute_on(view)` (transform a view, pushing history),
`execute_on_image(image)` (headless, no history), `execute_global(app)` (multi-frame operations
producing new windows — `Integration`, master building; 17 of the 141 processes), and
`execute_preview(image)` (non-mutating, for the real-time preview). `app.run(process)` dispatches
global versus active view. `Process.cache_values` lets a process **exclude** parameters from its
cache fingerprint when they only change a judgement, not a computation — see `SubframeSelector` in
§ 6.

**`Parameter`** descriptors come in `real`, `int`, `bool`, `enum`, `str`, `view`, plus table and
block forms for variable-length and raw data. Each has a **stable id**, which is the serialization
key — renaming one breaks every stored recipe and project. `visible_when` gives conditional
visibility in the auto-generated form; it is pure UI convenience, the value still travels at
execution time. **The GUI generates its panel from this schema alone.** There is no hand-written
process panel.

`view` deserves a word, because it is a type that adds no behaviour. To the domain it *is* a
`str` — same coercion, same serialization, same replay, and a headless script assigns a plain
identifier. What it states is what the string designates, and that is enough for the generated
form to offer the open views. The 28 parameters concerned were free text, so combining SHO meant
recalling three identifiers from memory — and a typo did not fail, the domain falling back on the
current image. A test walks the labels and refuses a parameter that names a view without carrying
the type.

When choices are only knowable at run time — the AI models installed, the 54 spectral curves plus
whatever the user dropped in `config_dir()/spectra` — the class answers
`parameter_choices(param_id)`, which the server consults on **every** projection of the schema. A
static `choices` tuple would be frozen at import.

**`STF`** never touches pixels. Per channel: `[midtones, shadows, highlights, low_range,
high_range]`, applied through the Midtones Transfer Function. `Image.compute_auto_stretch()`
derives one from robust statistics (median + MAD). `HistogramTransformation` shares the same
model, which is what makes "apply the current screen stretch permanently" a one-liner rather than
a special case — `app.apply_stf()` is that line: it builds the process from the view's STF,
applies it through `app.apply` (so it is an ordinary, undoable history entry echoing the process
itself), then resets the STF, without which the stretch would be displayed a second time on top
of the pixels that now carry it. The auto-stretch being computed **per channel**,
`HistogramTransformation` carries an optional flat list of per-channel triples; empty — the
default — means the three scalars on every channel, which is what it always did.

### `History` and `ProcessContainer` — `python/retina/process/container.py`

`ProcessContainer` is an ordered, replayable pipeline of instances — the reproducible *recipe*
primitive. It executes on a `View` (one history entry per step) or on an `Image` (headless), and
serializes to XML and to Python source.

Two capabilities matter and shape the design. A step can be **disabled** (to try the recipe
without it) and given a **mask of its own**. Both are addressed *by index* (`enable(i)`,
`set_mask(i, mask_id, invert)`), which leaves `processes` untouched and serializes cleanly. The
mask is designated **by view identifier, never by its pixels** — a recipe must remain a document.
It is resolved at execution time by a `resolve_mask` callable passed in; without that parameter
the domain would need a reference to the application, and the container would stop being testable
on its own.

### The process registry — `python/retina/process/registry.py`

Processes declare themselves through the **`retina.processes` entry-point group** (the napari
plugin model): a third-party package adds processes without modifying Retina. A direct-import
fallback guarantees the bundled processes are always available, even from an uninstalled source
tree.

On top of that sits a **user process directory** (`config_dir()/processes/*.py`, loaded by
`load_user()` at the end of `load_builtin`, errors isolated per file) — the plugin model without
the packaging. Registration fires `registry.on_changed`, which is how the GUI catalogue — fetched
once per session — refreshes when a process appears mid-session.

### On process names

Many process names are deliberately the conventional ones from the field —
`HistogramTransformation`, `MultiscaleLinearTransform`, `SCNR`, `StarAlignment`,
`LocalNormalization`, `DynamicPSF`. This is intentional: astrophotographers arriving from an
established suite should find a familiar API and not have to relearn a vocabulary. The
implementations are ours; the names are the domain's.

### Catalogue

141 processes across 26 categories. The heaviest are colour calibration (13), image inspection
(12), intensity transformations (11), multiscale processing (9), and colour spaces, background
modelling and geometry (8 each). The algorithmic work leans on the Python astronomy ecosystem
(the `[astro]` extra), wrapped as processes with **lazy imports** — scipy, scikit-image,
photutils, ccdproc, astroalign, astroscrappy, sep, reproject, PyWavelets, OpenCV, scikit-learn,
rawpy, astroquery, `astrometry` for offline plate solving.

Lazy imports are load-bearing for startup time, and they have a packaging consequence — see § 14.

---

## 6. Automated pre-processing — `retina.pipeline`

A pure-domain batch pre-processor: `scan(folder)` → `plan(inventory, preset=…)` → `run(plan)`.
Available headless (`python -m retina.pipeline /data/M31`) and from the GUI, through the same
facade (`python/retina/pipeline/facade.py`).

### Why the plan is not a `ProcessContainer`

A `ProcessContainer` is a linear recipe applied to **one** view. A pre-processing run does two
things it cannot: execute *global* processes (`Integration` reads N files and produces one) and
*multiply* one recipe over every frame of a group. So `Plan` orchestrates, and `ProcessContainer`
remains the brick of every per-frame step, reused as is. Nothing is reinvented, and any step
exports as an ordinary recipe to be replayed by hand.

### Built by phases, not by group

Steps are produced phase by phase — all master biases, then all darks, then all calibrations —
and not group by group. This is not cosmetic: the registration reference frame must be **common
to every filter**, failing which the L, R, G and B layers will not superimpose at composition
time. *All* measurements must therefore happen before the first registration.

### File to file

Everything runs under `<folder>/retina_pipeline/{masters,calibrated,registered,integrated}`. A
hundred 50 Mpx lights do not fit in RAM; resuming after an interruption becomes free; and every
intermediate opens in Retina to be inspected.

### Late bindings

Two values cannot be known at planning time: which frame will serve as the reference, and what
weights will come out of the measurements. The steps concerned declare them as tokens —
`@reference`, `@weights` — in their `bindings`, and the runner resolves them along the way. The
plan therefore stays entirely serializable and entirely readable, and the user sees explicitly
what will be decided en route.

The runner picks as reference the frame showing **the most stars**, among the finest binning. The
criterion is counter-intuitive — one would reach for the best FWHM — but what a reference must
provide is the largest number of landmarks to match, not the prettiest image.

### What can be edited, and what cannot

The plan **is** editable: `pipeline.set_step_params`, `pipeline.set_hooks`, `pipeline.set_criteria`.
Validation is the real work there. `Process.__init__` rejects unknown keys and coerces types but
**looks at neither `choices` nor bounds**, so an absurd value used to slip in silently and fail
three hours later, inside a worker thread. The editing layer validates against the schema.

What is **not** editable is the list of steps. It is the preset's contract, and the plan is a
graph in which one step's `inputs` are the previous step's `outputs` — disabling registration
would make integration read files nobody writes. To change the composition, change the preset and
rebuild.

### Hooks

`PlanStep.hooks` runs Python before and after a step. They are entrusted to the `Script` process,
from which they inherit the SHA-256 fingerprint, cancellation and the echo — no new extension
mechanism to invent. Two consequences that are not visible from the outside: the script's
**content** enters the step's cache fingerprint (editing it replays the step; otherwise one would
believe the new version had been applied), and `after` runs **before** `write_manifest` — a
failing hook leaves the step to be replayed rather than a cache asserting completed work.

### Grouping

`python/retina/pipeline/groups.py`. **Hard** criteria, required for every frame type: same
geometry, same binning, same **gain**, same rig (`INSTRUME`/`TELESCOP`).

Gain deserves naming: it sets the electrons→ADU conversion, hence the amplitude of the dark
signal *and* the read noise. A master dark built at gain 100 corrects nothing at gain 300, and
dual-gain rigs (narrowband high, RGB low) are common. Rig identity serves the same purpose: two
telescopes carrying the same camera produce frames indistinguishable by geometry but with
incompatible flats.

Then, per type:

| type | filter | exposure | why |
|---|---|---|---|
| light | yes | yes (±2 s) | what gets integrated together |
| dark | **no** | yes (±10 s) | the shutter is closed; the filter is meaningless |
| flat | yes | **no** | auto-brightness flats vary without changing meaning |
| bias | **no** | **no** | zero exposure |

Temperature is an additional criterion with a wide tolerance: a dark at +20 °C does not calibrate
a light at −10 °C, and the oversight is frequent. `SESSION` is deliberately **excluded** from a
group's identity — splitting by night would prevent integrating two nights of the same target.

Calibration matching (`match_calibration`) covers lights **and** flats. Three rules worth
spelling out: the bias enters a light's chain only if it serves (a master dark already contains
it); scaling a dark requires extracting its **dark current** first, because multiplying a master
dark by 0.5 would also halve a bias that does not depend on exposure time; and a flat is
calibrated by a flat-dark *or* by a bias, never both.

### Overscan and supplied masters

Overscan is detected in the header (`BIASSEC`/`TRIMSEC`, the IRAF convention) and corrected right
at the front, on every frame type. This is not a refinement: on the first real sensor tried,
correcting or not changed the final sky background by 30 %.

A **master supplied by the user** (pattern `master` in the path) is reused as is rather than
rebuilt — the run cache does not cover that case, it only knows our own outputs. Conversely, the
masters the pipeline writes carry their full identity (`IMAGETYP`, `EXPTIME`, `FILTER`, `GAIN`,
temperature, rig), which is what allows re-reading them from a library and regrouping them under
the key that produced them.

### Integration: adaptive rejection, row bands

Rejection is adaptive: percentile clipping below six frames, winsorized up to fifteen and for all
masters, linear fit beyond. **The plan freezes the mode chosen** rather than deciding at run time
— a replayed plan must give the same result.

Integration proceeds by **row bands** (`io/lazy.py` reads FITS through `memmap`): a hundred 50 Mpx
subs do not fit in memory, and the result is bit-identical to the in-memory computation.

### Excluding a frame versus not stacking it

Two notions that must never be conflated.

- **Exclude from the project** — `pipeline.exclude` — removes a file from the whole chain: wrong
  type, corrupt, wrong target. This is the Blink panel's gesture, which looks at raw frames.
- **Do not stack this sub** — `pipeline.set_rejects` — still calibrates and registers it; it
  simply weighs zero. This is the selector's gesture, which judges **after** measurement.

The difference is not theoretical: the first changes the inputs of calibration, measurement and
registration, and therefore invalidates their caches.

That is exactly why `SubframeSelector` separates **measuring** (`measure_raw`, expensive — one
star detection per sub) from **judging** (`evaluate`, microseconds), and why `Process.cache_values`
exists. Rejecting six subs out of a hundred then recomputes only the integration.

### Measurement and caching

Frame quality comes from fitting an **elliptical Gaussian** to the stars
(`processes/psf.py::fit_psf_stars`, shared with `DynamicPSF` — two implementations would have
diverged on the very quantity used for sorting). FWHM was previously a proxy derived from
DAOStarFinder's "sharpness", which is not a full width at half maximum. Two traps are worth
knowing: photutils **freezes** the shape parameters of its PSF models (they target photometry at
known PSF), so an unprepared fit returns the initial value while looking converged; and a fit on
a flat region converges just as convincingly, hence the requirement that the model's peak exceed
the local dispersion. The elliptical **Moffat** profile is ours — astropy and photutils ship only
a circular one, which would render no eccentricity at all.

Measurements are cached **per file**, not per step (`pipeline/measure_cache.py`), at user scope.
That is what makes adding a night incremental: the run cache puts the frame list into its
fingerprint, so adding twenty subs used to re-measure a hundred and twenty. The measurement
cache's key deliberately excludes `frames` — otherwise it would never hit.

Approval expressions receive `_min`, `_max`, `_median`, `_sigma` and `_n` per measurement. **To
reject, use `_sigma`** — deviation from the median in robust dispersion (MAD × 1.4826). `_n` is a
min-max normalization: a single bad sub squashes all the good ones against 1 and makes them
indistinguishable. It remains the right choice for *weighting*, where "1 = the best of the batch"
is exactly what is wanted.

### Smart telescopes, dual-band, framing mode

Seestar and Dwarf have their own presets, and they are not labels: their sensor is unregulated,
so `temperature_tol` opens to 100 °C — the 5 °C default produced one dark group per exposure. A
one-shot-colour camera under a **dual-band** filter is *not* debayered (interpolating would mix
Hα and OIII inside every pixel, irrecoverably); `ExtractDualBand` separates the two lines by
superpixel, and each band becomes a light group in its own right, so downstream phases apply
without knowing anything about it.

**Framing mode** produces mosaics: lights are grouped into panels by clustering on angular
separation, computed with the haversine formula (comparing raw RA values diverges near the
poles); each panel is integrated then solved, and `MosaicReproject` assembles them. Two accepted
consequences: plate solving, elsewhere off by default because it downloads index files, is **on**
here (no WCS, no mosaic); and the **registration reference becomes per-panel** — the one-reference
rule exists so L/R/G/B superimpose, but between disjoint panels it would demand matching stars
that have no reason to be the same ones.

### Robustness

One frame that fails does not carry off the batch. A truncated file, a sub where star matching
does not converge: over several hundred frames, that *happens*, and interrupting three hours of
computation for one frame in two hundred would be the worst possible behaviour. The offending
frame is set aside, the reason recorded in the report, and later steps no longer see it. Only an
explicit `ProcessCancelled` really interrupts; an entirely lost group raises.

---

## 7. The web shell

`python/retina/server/` (Python) + `web/` (TypeScript) + `crates/retina_shell/` (native window).

Python is the **host**: `python -m retina.web` starts the server, then launches the native
window, which loads the server's URL. The shell is optional; the server package is never imported
by the core.

### Why tao + wry rather than Tauri

The frontend is not served by an asset protocol — it comes from a **remote HTTP origin**
(`http://127.0.0.1:PORT`, served by aiohttp). Tauri v2 deliberately restricts its IPC for remote
origins through the *capabilities* system, which is a permanent fight for an architecture where,
by construction, everything already goes through the Python server. Tauri's bundler, updater and
plugin system are of no use here either: packaging is briefcase's job. What remains needed is
exactly the window and the webview — tao and wry, the two blocks Tauri is itself built on, built
by a bare `cargo build` with no CLI. Should a Tauri plugin ever become indispensable, the
migration is mechanical: it is the same stack underneath.

### Complete snapshot, not fine-grained events

The domain emits **nothing**: no "process applied", no "view modified", no "history changed". Only
`on_echo`, `on_windows_changed` and `ViewportState.on_change` exist. Guessing what changed after
each call would mean instrumenting ~140 processes and every method of `app` — a lot of fragile
code to save a few kilobytes.

The complete snapshot is a few KB even with ten windows open, goes out **at most once per loop
turn** (`Broadcaster` coalesces bursts), and lets the frontend be a plain `render(snapshot)`
function. The only bulky data — the pixels — is excluded and travels over HTTP.

### `pixel_gen`

Every view exposes a counter that increments as soon as its numpy array is no longer *the same
object*. `end_process`, `undo`, `redo` and `go_to` all replace `View._image`, so the counter moves
mechanically with no line added to the domain. Tracking uses a **weak** reference: a strong one
would keep every image of every history alive.

Accepted limitation: an **in-place** mutation (`Image.set_sample`) does not change array identity
and would go unnoticed. `SnapshotBuilder.invalidate()` exists to be called explicitly in that
case.

### Bulky per-view data stays out of the snapshot

The corollary of the complete snapshot. `View.properties` — `DynamicPSF` measurements and whatever
follows — publishes only a **summary** into the snapshot, `{rev, keys}`; the content is fetched by
`app.view_property` and the client re-requests it when `rev` moves. Hundreds of stars × N views on
every `state.changed` would cost tens of KB per burst, for data only an open panel looks at. **Any
bulky data attached to a view must follow this pattern.**

### Pixel transport

float32 → float16 introduces at most **0.043 LSB** of deviation after STF — 23× below the
visibility threshold, on very dark linear data where intuition says the opposite (float16 is
*floating*: its precision is relative, and a sky background around 1e-3 stays far above the
subnormals). Transport is therefore halved for free, and half-float textures are filterable in
base WebGL2 where float32 requires `OES_texture_float_linear`.

**No STF LUT.** The STF is evaluated analytically in the shader — `mtf()` is a closed form — so it
travels in the JSON snapshot as three numbers per channel, and nothing binary. The 4096-entry LUT
this replaced cost ~11 LSB in the shadows under auto-stretch (measured).

Large images are served through a **lazy pyramid**: `?scale=S` (a power of two) serves reduced
level S, `?rect=` a tile. Beyond `MAX_TEXTURE_SIZE` the viewport composes an overview plus tiles.

The URL carries the generation (`?gen=N`), so invalidation is done by changing address and a stale
generation answers **409** rather than obsolete content. See § 15 for the cache trap that made
this necessary.

### Four smaller rules

- **The real-time preview carries the view it represents** (`rtp.ready["view"]`), and the panel
  renders the before/after curtain and the STF from *that* view, never from the active one: the
  two diverge the moment you switch views mid-computation, and the curtain then compared two
  different images without saying so. The preview is shell plumbing — non-mutating, no echo, like
  `layout.*` — and console parity lives at the right level, `Process.execute_preview(image)`.
- **Zones are derived from panels, never mirrored.** `app.layout.toggle_zone('sidebar')` folds a
  *zone*; the server alone remembers which panel to reopen (`WebLayoutBackend._zone_memory`). Do
  not duplicate that memory in TypeScript.
- **The filesystem is the server's job** (`server/handlers_fs.py`). The native shell returns
  **paths**, never bytes; making it read a file would create a capability the console does not
  have. `fs.*` does not widen the security model — the IPython console already gives the whole
  disk — it *types* that access and bounds it against accident.
- **Shortcuts are derived from the command registry** (`web/src/shell/keybindings.ts`): a
  `Command.shortcut` is wired by construction, and duplicates throw. Do not put a hard-coded
  `keydown` back into a component — except for a **contextual** shortcut installed by Monaco
  inside an editor and marked `localShortcut` (F5 runs the script there, applies the last process
  elsewhere).

### Build-chain versions worth knowing

- **Monaco is imported subpath by subpath**, and 0.56 added an `exports` map that made every
  `monaco-editor/esm/vs/...` path resolve to nothing. Nineteen of the twenty imports there are
  side-effect only — the contributions that supply Ctrl+F, folding and hover — so the build
  stayed green while the features disappeared. `noUncheckedSideEffectImports` is on in
  `tsconfig.json` for that reason, and the e2e exercise Ctrl+F and Ctrl+/ for the part typing
  cannot prove. The per-language entry point is `languages/definitions/<lang>/register`; the
  `basic-languages` replacement pulls all ninety languages at once.
- **Vite stays at 7.** Under 8 the asset graph loads differently and two pointer-gesture e2e
  break — the crop drawn with the mouse moves the frame instead of drawing it. Both are timing
  fragilities on our side rather than Vite bugs, but they are a piece of work, not a bump, and
  Vite 7 carries no advisory. Do not merge the Vite 8 Dependabot pull request without running
  `npx playwright test` and reading this paragraph.
- **The Monaco theme reads *computed* CSS variables**, so it gets whatever the minifier emitted.
  `styles/tokens.css` writes `#cccccc`; a minifier may hand back `#ccc`, which Monaco rejects
  with `Illegal value for token color`. `readToken` expands the shorthand — do not "simplify" it
  back to a bare `replace('#', '')`.

### Security posture

The server listens on loopback and drives the whole application, including arbitrary Python
through the console. Loopback is not a security boundary on the browser side (DNS rebinding), so
two protections, both necessary. **A token** drawn at startup and passed in the initial URL,
accepted in three forms — cookie `retina_token` (for requests the browser issues on its own,
`<script src>`), header `X-Retina-Token` (for frontend `fetch`; it works through the Vite dev
proxy, where a cookie would not follow), and `?t=` (for the initial URL and the WebSocket, whose
browser API allows no custom header). And an **`Origin` check** on the WebSocket: the token alone
is not enough, since a page that had guessed or leaked it could open a cross-origin WS,
WebSockets not being subject to the same-origin policy.

---

## 8. GPU dispatch — `python/retina/backend/xp.py`

**Dispatch follows the type; policy is decided at mount time.** These are two responsibilities and
they must not be conflated.

- `get_array_module`, `ndimage_for`, `fft_for` and `to_numpy` look at *what they are given* and
  nothing else. A CuPy array routes to cupy, full stop — even with the GPU switched off,
  otherwise there would be no way to bring it back down.
- **`to_device` is the only mount point**, and the only place that consults the kill switch
  (`RETINA_GPU=0`), the user preference, CuPy's availability and the size of the data
  (`GPU_MIN_PIXELS`).

The bug this separation avoids: a single `is_gpu` mixed type and policy, so with a genuine CuPy
array and `RETINA_GPU=0` it returned `False` — `get_array_module` then returned numpy, and
`np.pad(cupy_array)` raised. `to_numpy` broke the same way, which made the kill switch unusable at
the exact moment it was needed.

`GPU_MIN_PIXELS = 100_000` is **measured, not guessed**. Total variation is the more sensitive
candidate because one iteration costs little: it loses at 0.01 Mpx (×0.2), catches up around
0.05 Mpx (×0.8), pulls ahead at 0.1 Mpx (×1.4). Richardson-Lucy wins from 0.02 Mpx (×1.8) because
one iteration there costs two FFTs. 100,000 pixels is where the less favourable of the two stops
losing.

Other rules:

- A ported process **mounts as close to the computation as possible and comes straight back
  down**. The model stays numpy; downstream code does not change.
- **Never import cupy at module level.**
- `to_device` never raises: no GPU, memory full, angry driver — the input comes back unchanged and
  the computation happens on the CPU, which is slow but correct.
- A scalar read back from the device (`float(x)`, `if x > 0`) is a **hidden synchronization**. In a
  loop it cancels the gain entirely.

Measured on an RTX 5080 at 24 Mpx: Richardson-Lucy ×35, total variation ×39. On the CPU side, the
Rust `_core.tgv_denoise` is ×19.5 over the numpy path. GPU support is opt-in (`pip install
-e '.[cuda]'`) and the CPU path remains the reference.

---

## 9. Internationalisation

**Two toolchains, one per layer.** Do not mix them.

### Frontend — Paraglide JS (inlang)

Catalogues live in `web/messages/{en,fr}.json` (versioned); `npm run messages` compiles them into
typed functions under `web/src/paraglide/` (gitignored). Usage: `import { m } from '…/paraglide/messages'`
then `m.my_key()`, or `m.my_key({ param })` for a message with holes. **A missing key is a `tsc`
error** — which is what makes the guard half free. Keys are `snake_case`, prefixed by domain
(`cmd_`, `cat_`, `menu_`, `panel_`, `status_`, `selector_`, `pipeline_`, `prompt_`, `dialog_`,
`viewport_`, `script_`…).

### Python — stdlib gettext

`python/retina/i18n.py`. Babel is a **development-only** dependency
(`scripts/update_translations.py` extracts, merges and compiles). **msgids are English**, per
gettext convention: the domain and the console see English, and a third-party process with no
catalogue stays readable.

- `_t("…")` translates immediately.
- `N_("…")` marks without translating — for text written at class-definition time and translated
  later (parameter labels, translated in `server/handlers_process.py::_parameter`).
- **Not `_`**: the repository already uses it as a throwaway variable, and a loop would reassign
  the translation function.

The compiled `.mo` is **versioned**: maturin copies `resources/**` verbatim, and a missing
catalogue would make the application speak English *silently*.

### The server is the authority

The client guesses a language at startup (`localStorage` mirror → the shell's `locale` IPC →
`navigator.language` → English), then adopts the one from `hello` by **reloading** if they differ
(`web/src/shell/locale.ts`). The reload is not a stopgap: the label tables (`commands.ts`,
`panels.ts`) are built at module import, and it also redoes the `process.list` the client only
asks for once per session. Hence the two-file bootstrap — `main.tsx` resolves the language, *then*
imports `app.tsx`.

### Source code is English; French survives only in the product catalogues

**This is the current convention and it is enforced.** Comments, docstrings, variable, function,
class and test names, log messages, CLI `--help`, RPC error messages and commit messages are all
**English**. Never write French in a source file.

French exists in exactly **three product catalogues**, which are features rather than residue:

| Catalogue | Content |
|---|---|
| `web/messages/fr.json` | frontend UI strings |
| `python/retina/resources/i18n/fr/**` | Python gettext catalogue (`.po` + `.mo`) |
| `python/retina/resources/doc/*/fr.md` | French process documentation |

The only exceptions to English source are assertions that **verify** those catalogues
(`tests/test_i18n.py`, `tests/pipeline/test_plan.py`, `web/e2e/*.spec.ts`) and the French key
aliases in `web/src/shell/keybindings.ts`, which are functional.

`python scripts/check_english.py` measures the state and must report zero; `--strict` exits 1 for
CI. It uses three probes, because no single one suffices: accented characters (with an allowlist
derived from the project's own English content — `à-trous`, `Pérez`, `moiré`, `Hyvärinen`),
French bigrams and elisions — single stopwords were tried and abandoned, since `la`, `si`, `on`,
`est`, `pas` collide with English and with code far too often, whereas two-word sequences and
apostrophe elisions do not — and French **identifiers** by AST walk, which have no textual
signature at all. (The bigram list lives in the script rather than being quoted here: spelling the
patterns out in this document would make the document itself an offender.)

### What does not get translated, and the guards

Python echoes (they are code), domain identifiers (panel ids, `process_id`, enum `choices`,
perspective names), MCP tool descriptions (a machine interface — translating them would make the
agent's contract vary with the server's locale), `console.*` output and internal errors.

Two guards: `web/tests/i18nGuard.test.ts` (no French text and no hard-coded UI attribute in
`web/src/`) and `tests/test_i18n_guard.py` (every `label=`/`tooltip=` under `N_`, msgids free of
accents, the `fr` catalogue complete and the `.mo` up to date). The pytest suite and Playwright's
`webServer` both pin `RETINA_LANGUAGE`: without that, a test asserting a server string would pass
or fail depending on the machine's `LANG`.

---

## 9 bis. The documentation, and why it is domain data

`python/retina/documentation.py` is a **domain** module: the console and the GUI consume the same
pages the same way. Sources live in `python/retina/resources/doc/<PageId>/{en,fr}.md`, where a
page id is either a `process_id` or `_guides/<slug>` — a class name can hold neither a leading
underscore nor a slash, so the two namespaces cannot collide and one identifier travels through
`retina.doc()`, `render_page`, the `retina-doc://` links and the HTTP routes. Everything ships in
the wheel; KaTeX is vendored; nothing needs the network to be read.

Three things are **generated rather than written**, because a page that restates the code is a
page that will contradict it:

- the **`## Console` section** of every process page — class name, every parameter with its
  default, and the single `app.run(...)` that executes it, built from the registry and the
  `Parameter` schema. It is the reference statement of console/GUI parity (§4), which the
  catalogue used to describe only as a set of form fields. Three pages (`ConeSearch`,
  `MosaicPlanner`, `SurveyReference`) hand-write the section to show how to read `.result`; a
  heading already present wins, and nothing is appended.
- the **`related` chips** under the header, from the frontmatter — validated by the tests since
  the beginning and, until now, rendered nowhere.
- the **figures**, produced by running Retina on real data (`scripts/gen_doc_figures.py`, a
  deliberate act; one spec module per process under `scripts/doc_figures/`, written against the
  public API so each doubles as an executable example). A screenshot is a claim about the code
  that nothing keeps true; a regenerable figure is not. Storage is in-repo under
  `<PageId>/figures/*.webp`, with a per-image and a total ceiling enforced by `tests/test_docs.py`
  — the docs travel inside the wheel, and PixInsight's 184 MB documentation tree is the
  cautionary tale.

Figures are referenced **relatively** (`figures/before.webp`) so the same Markdown works from
disk and over HTTP. The viewer writes the page into an `iframe` with `document.write`, where a
relative URL resolves against the application: hence `render_page(media_base=…)`, which rewrites
`src` attributes only, and the `/api/doc-media/` route. A `<base href>` would have been shorter
and wrong — the pages carry a table of contents whose `#` anchors it would send out of the frame.

`documentation.search()` scans the pages of one language in memory (`lru_cache`), weighting
title, keywords and body, requiring every term, and **folding diacritics**: half the catalogue is
French and a search box is typed at speed, so an unaccented query has to find the accented word.
Exposed as `retina.doc_search(...)` and over `/api/doc-search`; the corpus is small enough that
an index would be machinery to maintain rather than time saved.

---

## 10. MCP server and the built-in assistant

### MCP server — `python/retina/server/mcp/`

`python -m retina.web --mcp` mounts a Model Context Protocol server on `/mcp`, so that an agent
can inspect the session, open images, apply processes and launch a pre-processing run **inside the
session the user is looking at**, not in a copy. `python -m retina.mcp` serves the same thing over
stdio, with no shell.

MCP is a **client of the API**, exactly like the web shell and the console: no tool contains
logic, each delegates to an existing handler or to `app.*`. Design points:

- **The tool registry is separate from the transport** (`mcp/tools.py`). The in-app chat panel
  calls it directly, in-process, without speaking MCP — otherwise there would be two definitions
  of the same tool, diverging at the first addition.
- **The transport is written by hand on aiohttp**, not taken from the `mcp` SDK (ASGI/Starlette).
  The server side of the protocol is JSON-RPC 2.0 with about ten methods, which `server/rpc.py`
  already does, whereas an ASGI bridge or a second port would break the "one port, one token,
  loopback" model of `security.py`.
- **Every mutating tool returns its Python echo.** The agent learns the API by acting, exactly as
  a user watching the console does, and what it returns is copyable into a script. Hence the
  fan-out from `ServerApp._on_domain_echo` to `echo_listeners`.
- **The catalogue is read in two stages**: `list_processes` returns one line per process,
  `describe_process` the schema of a single one. Dumping 141 schemas would cost tens of thousands
  of tokens per conversation. Same reason for `get_state`'s projection and `get_stats`'s 64
  default bins. `tests/server/test_mcp.py` holds a size guard that breaks if one tool too many is
  added. There are currently **18 tools**.
- **Pipeline inventories and plans do not cross the context**: the server keeps them and returns a
  **handle** (`inv1`, `plan1`). This is the only divergence from the `pipeline.*` handlers, which
  pass them to the client — because the web shell displays them.
- **`render_view` is what gives the agent eyes**: block-mean downsampling **then** STF, never the
  other way round (a 6000×4000 float32 sub weighs 274 MiB), and mean rather than decimation —
  taking one pixel in N makes the stars disappear, and the agent would conclude the field is
  empty.
- **Mounted by default with the web shell, separate token.** `/mcp` is mounted by
  `python -m retina.web` (`--no-mcp` turns it off; `ServerApp` keeps `mcp=False` by default for
  tests). The posture is unchanged: loopback plus token required, and the **persistent token**
  (`config_dir()/mcp-token`) opens that route only — such a request does **not** receive the
  session cookie, which would give it the rest of the server. `--mcp` prints the configuration to
  paste into an external agent.

### Built-in assistant — `server/chat.py` + the `chat` panel

The **Assistant** panel is a chat whose engine is **the `claude` CLI the user installed and
signed in to themselves** — their own subscription, not an API key. This is a constraint rather
than an implementation preference. The panel detects three states (absent → installation
commands; not signed in → `/login` guidance; ready) via `claude --version` and `claude auth status`.

- **One `claude -p` process per turn**, continuity through `--resume <session_id>`. Interruption is
  a `terminate()` — portable, no control protocol needed. A killed turn does **not** persist its
  session id: we resume from the last complete turn.
- **The agent's surface is bounded in the argv** (`tests/server/test_chat.py` holds it):
  `--tools ""` (no built-in tools), `--allowedTools "mcp__retina__*"` (ours, auto-approved),
  `--strict-mcp-config` and `--setting-sources ""` (neither the user's own instructions and hooks
  nor their other MCP servers), never `--dangerously-skip-permissions`, and no `ANTHROPIC_*`
  variable injected.
- **The stream-json format is not contractual**, and that is handled rather than hoped about.
  `chat.py::_parse_line` is the only place that knows it, and is tolerant: an unknown type is
  ignored and logged. A turn where **no** line was understood returns the `unparsed_stream` reason
  rather than a bare error, which the panel turns into "update Retina" — otherwise the user cannot
  guess where the failure comes from. `tests/server/test_chat_contract.py` replays the invariants
  against the **real** binary; it sits outside `pytest -q` (quota, seconds, a signed-in CLI) and is
  enabled by `RETINA_CLI_CONTRACT=1`. **Run it after every CLI update.** Version bounds are
  similarly graduated: below `CLI_MIN_VERSION` the panel refuses with a screen that says what to
  do, above `CLI_TESTED_MAX` it warns without blocking, and an unreadable version never blocks — a
  doubt about a number is not a refusal.
- **The server sends structure, the client composes the labels** (typed `chat.event`; paraglide
  `chat_tool_*`): conversation content is not translated, chrome is translated where paraglide
  lives. Persistence is `config_dir()/chat-session.json` — the CLI keeps the context, we keep the
  display.

---

## 11. File formats and projects

**FITS** through `astropy.io.fits`, WCS included. **Camera RAW** through `rawpy`. Raster export
(TIFF float32, PNG, JPEG, JPEG 2000, WebP, JPEG XL) in `io/raster.py`.

**One dispatch point**, `io.save_image`, which `app.save` delegates to rather than duplicating —
it did, and the duplicate knew FITS and XISF only, so a processed image could not leave as a PNG
while `io.raster.save_raster` sat there with no caller. The extensions are grouped in `retina.io`
(`ASTRO_EXT`, `FLOAT_RASTER_EXT`, `BYTE_RASTER_EXT`) and **published in the `hello` handshake**:
the frontend builds its file dialogs from that instead of a list of its own, which had already
drifted.

The byte group carries a warning worth stating, because it is the difference between what the
screen shows and what a file holds. A linear image has its sky background around 1e-3, so an
8-bit export of one is black — while the viewport, applying the screen transfer function, shows a
nebula. `app.save(path, stretch=True)` bakes the STF into **the exported copy only**, and the
interface asks which was meant when the target quantizes and a non-identity STF is displayed.
FITS, XISF and float TIFF never ask: they carry the linear data faithfully.

**XISF** is the native interchange target. It is an open, documented specification, independent of
any single implementation
(<https://pixinsight.com/doc/docs/XISF-1.0-spec/XISF-1.0-spec.html>): a monolithic file is an XML
header plus binary blocks, supporting compression (Zlib/LZ4/Zstd with byte-shuffle variants),
checksums, typed properties, FITS keywords, ICC profiles, CFA description and an embedded screen
transfer function. Read and written through the PyPI `xisf` library.

**Projects** are a single `.retina` file — HDF5 — holding a whole session: windows, previews,
masks, STFs, WCS, keywords, viewport, and **every history state**, so undo and redo survive
reopening (`python/retina/io/project.py`).

- A project is a **document**: it gets copied, moved, sent. A folder of a thousand small files
  breaks on the first incomplete transfer; HDF5 gives one chunked, compressed, partially readable
  file, readable with any HDF5 tool should Retina ever disappear. The manifest is a **dataset**,
  not scattered attributes — HDF5 attributes top out around 64 KB, while a single JSON blob
  versions cleanly and stays readable with `h5dump`.
- The filter is **gzip level 1 + shuffle**, not an exotic codec. Shuffle is what makes astronomical
  float32 compressible; gzip is in the HDF5 core, hence readable everywhere; level 1 keeps writing
  fast. An external filter (zstd via `hdf5plugin`) would make the file unreadable without the
  plugin installed — unacceptable for a document format. Shared history states are written once
  (dedup by array identity).
- An **unknown `process_id`** at load time becomes an `UnknownProcess` (the dict kept and
  reinjected verbatim) rather than preventing the project from opening.
- The shell's document blob — script tabs with their unsaved buffers, recipes, transcript — travels
  through the perspective mechanism, the server *asking* the client for it during the write. The
  domain never interprets it, which is what lets `open_project` followed by `save_project` in pure
  console carry the user's tabs across without knowing anything about them.

---

## 12. Conventions

### Python

3.11+, type hints everywhere, `ruff` (lint + format), `mypy`. The domain (`model/`, `process/`,
`io/`) does not depend on the shell — strictly separated to keep the core scriptable and headless.

The ruff rule set is **explicitly selected** in `pyproject.toml` rather than left to defaults,
which change between versions: moving to ruff 0.16 otherwise surfaced ~300 diagnostics at once on
unchanged code. Pinning the set makes upgrading ruff free of surprises.

### Rust

Edition 2021, `ndarray` + `rayon` for multicore, PyO3 with `allow_threads` to **release the GIL**
on long operations. Zero-copy numpy interop through the `numpy` crate. The core is built as
**abi3-py311** — one wheel for 3.11+.

### Threading — the hard rule

Long processes run in a `ThreadPoolExecutor`; the UI never freezes (progress bar plus
cancellation). **A worker never touches a WebSocket directly.** Everything heading back to the UI
— echo, viewport refresh, progress — goes through the asyncio loop
(`Broadcaster.post` → `loop.call_soon_threadsafe`, `server/broadcast.py`). This is the literal
transposition of "a worker never touches a widget".

The `Broadcaster` also **merges bursts**: one user action often produces several mutations
(`select_view`, then `compute_auto_stf`, then `set_zoom`). Emitting a full snapshot each time
would send three states, two of them already stale. `mark_state_dirty` raises a flag and the
snapshot is built and sent once, on the next loop turn. The "already scheduled" guard is a
**boolean**, not the handle returned by `call_soon_threadsafe`: the handle is known to the caller
only *after* the call returns, by which time the loop may already have run the callback — we would
then overwrite the `False` set by the flush with a consumed handle, and no snapshot would ever go
out again.

`ProgressMonitor.report` doubles as a cancellation point, so instrumenting a process for progress
gives it cancellation for free.

### Testing

| Layer | Where | What |
|---|---|---|
| Domain | `tests/` | headless, no shell. A process must be verifiable through `execute_on` on an `Image` with no interface. |
| Pipeline | `tests/pipeline/` | scan, grouping, plan construction, runner, caches |
| Server | `tests/server/` | JSON-RPC handlers, snapshots, MCP, chat — no browser |
| Frontend units | `web/tests/` | vitest; transform parity against fixtures produced by the domain, MTF, i18n guard |
| End to end | `web/e2e/` | Playwright smoke through a real browser |

`python scripts/gen_web_fixtures.py` regenerates the TypeScript parity fixtures — a deliberate act,
never automatic, since it is what pins the two implementations together.

GPU tests carry the `gpu` marker and skip themselves without a card (`pytest -m gpu`,
`pytest -m "not gpu"`).

### Third-party components

`retina/credits.py` plus `resources/credits.json` list every bundled third-party component —
versioned assets, npm packages inlined by Vite, crates linked into the shell, on-demand downloads
— with its licence and, where required, its full notice under `resources/licenses/`. **Python
dependencies are not listed by hand** but enumerated at run time from `importlib.metadata`: a
manual list would have drifted at the first `pip install`. `tests/test_credits.py` checks the
manifest covers what is actually on disk. Visible from the console (`app.credits()`) and under
Help → Licences.

One licensing point deserves attention: the GraXpert AI models are **CC BY-NC-SA 4.0** — free, but
commercial use forbidden — whereas Retina itself restricts nothing. The NC term comes from the
models, not from Retina, and follows them into the FITS keywords. `retina.ai.models` prefers, in
order, a local GraXpert installation used *in place* (no copy), then a Hugging Face mirror of the
unmodified models (SHA-256 verified, downloaded on demand — neither GitHub nor PyPI can carry a
218 MB blob), then an explicitly supplied `.onnx` path.

---

## 13. Repository layout

```
retina/
├── ARCHITECTURE.md           this file
├── README.md
├── LICENSE                   GPL-3.0-or-later
├── pyproject.toml            maturin build backend + briefcase packaging
├── Cargo.toml                Rust workspace
├── crates/
│   ├── retina_core/          Rust/PyO3 → the native module retina._core
│   └── retina_shell/         native window (tao + wry)
├── python/retina/
│   ├── app.py                the root `app` object — the single source of truth
│   ├── credits.py            bundled third-party components and their licences
│   ├── preferences.py        typed, persisted, echoed settings (app.preferences)
│   ├── i18n.py               gettext wrapper (_t, N_)
│   ├── model/                Image, View, ImageWindow, Preview, STF, ViewportState
│   ├── process/              Process, ProcessInstance, Parameter, registry, container
│   ├── processes/            the 141 concrete processes
│   ├── pipeline/             automated pre-processing: scan, groups, plan, runner, caches
│   ├── io/                   fits.py, xisf.py, raw.py, raster.py, lazy.py, project.py
│   ├── backend/              numpy/CuPy dispatch (xp)
│   ├── ai/                   ONNX model discovery and download
│   ├── server/               web shell: aiohttp, JSON-RPC, snapshots, IPython console, mcp/
│   └── resources/            process docs, Tabler icons, branding, i18n catalogues, webui/
├── web/                      TypeScript frontend (Vite + Preact + dockview + Monaco)
│   ├── src/                  api, shell, viewport, panels, processes, console, scripts, chat
│   ├── messages/             en.json, fr.json (Paraglide catalogues)
│   ├── tests/                vitest
│   └── e2e/                  Playwright
├── scripts/                  build_dist, fetch_astap, update_translations, check_english, …
└── tests/                    pytest: domain, pipeline/, server/, recipes/
```

---

## 14. Development commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install maturin
pip install -e '.[web,xisf,astro,project,dev]'

# Optional NVIDIA GPU. It MUST be opt-in: the CuPy wheel is tied to a CUDA branch (no PEP 508
# marker can condition on the driver) and exists only for Linux and Windows — adding it to the
# line above would make `pip install` fail outright on macOS.
pip install -e '.[cuda]'      # CUDA 13 (Blackwell included); '.[cuda12]' for an older driver

# Build and install the Rust core (abi3-py311: one wheel for every supported Python).
maturin develop --release

pytest -q                                        # domain + server, headless
pytest -m "not gpu" -q                           # skip the CuPy parity tests
ruff check python tests scripts

# --- headless usage ---
python -m retina.run recipe.py                   # a full pipeline with NO shell
python -m retina.pipeline /data/M31              # automated pre-processing
python -m retina.pipeline /data/M31 --plan-only  # inspect the plan before running
python -m retina.pipeline /data/M31 --preset osc --save-plan plan.json
RETINA_LANGUAGE=fr python -m retina.pipeline /data/M31   # pin the language

# --- translations ---
python scripts/update_translations.py            # extract → merge → compile .po/.mo (deliberate)
python scripts/update_translations.py --check    # report what is left to translate, write nothing
cd web && npm run messages                       # web/messages/*.json → src/paraglide/
python scripts/check_english.py                  # French burn-down; --strict exits 1 for CI

# --- web shell ---
cd web && npm install && npm run build   # frontend → python/retina/resources/webui/ (gitignored)
npm test                                 # vitest: transform parity, MTF, i18n guard
npx playwright test                      # E2E smoke (starts its own server)
cargo build --release -p retina_shell    # the native window
python -m retina.web                     # server + native window
python -m retina.web project.retina      # open a project at startup
python -m retina.web --restore-session   # reopen the previous session, and save it on exit
python -m retina.web --no-shell          # server only (browser / remote mode)
python -m retina.web --dev               # point the window at the Vite dev server (HMR)
python scripts/gen_web_fixtures.py       # regenerate the TS parity fixtures (deliberate)
python scripts/gen_icons.py              # regenerate .ico/PNG/favicon from the logo (deliberate)

# --- MCP and the assistant ---
python -m retina.web --mcp               # print the MCP config for an external agent
python -m retina.web --no-mcp            # disable /mcp (the built-in assistant included)
python -m retina.mcp                     # stdio, no shell
claude mcp add --transport http retina http://127.0.0.1:8765/mcp \
    --header "X-Retina-Token: <token>"   # token printed by --mcp
RETINA_CLI_CONTRACT=1 pytest tests/server/test_chat_contract.py -v   # after each CLI update

# --- profiling ---
python scripts/profile_hotspots.py            # Rust / GPU port candidates
python scripts/profile_hotspots.py --gpu

# --- packaging: the three ordered pre-steps, then briefcase ---
python scripts/build_dist.py                  # 1. frontend → resources/webui/, shell → retina/shell/
python scripts/fetch_astap.py                 # 2. (Windows) ASTAP + D05 database → vendor/astap/
maturin develop --release                      # 3. retina/_core into the tree
briefcase create && briefcase build && briefcase package
```

Reference development environment (2026-07): Python 3.14.6, Rust 1.94. Every dependency has 3.14
wheels. The published package supports 3.11+.

---

## 15. Packaging

Briefcase has **no pre-build hook**, so the non-Python artifacts must exist *before*
`briefcase create`. That is the three-step order above, and it is not negotiable.

A single mechanism carries everything: `sources = ["python/retina"]`. All three non-Python
artifacts — the built frontend, the native shell binary and the Rust core — live *inside*
`python/retina/`, so no additional packaging rule is needed. This is deliberate; do not move them
into a separate distribution folder.

`maturin develop` and not `maturin build`: `build` produces a wheel, which briefcase would not
know where to pick up. `_core` is built abi3-py311, hence compatible with whatever Python briefcase
embeds, as long as it is ≥ 3.11.

### The astro ecosystem is part of the bundle

The briefcase `requires` list must stay a mirror of the `[astro]` extra (minus `astrometry`, which
does not compile under MSVC — ASTAP replaces it on Windows, and the `.linux`/`.macOS` sections
reintroduce it).

This is not a size preference. Processes import scipy, scikit-image and photutils **lazily**,
inside their method bodies: a bundle without those wheels **starts fine**, displays all of its
processes, and dies with a `ModuleNotFoundError` on the first click. "The app launches" is
therefore **not** a packaging test. The smoke test that counts is applying a process from each
family in the *installed* application, driven through its MCP server — which is exactly what
revealed a bundle shipping without its astro ecosystem. Adding a dependency to a process means
adding it to `requires` too.

### `support_revision` — one line governs Python *and* OpenSSL

The Python runtime embedded in the Windows MSI does **not** follow the development Python. Without
an explicit pin, briefcase takes its template's `support_revision`, and the MSI genuinely shipped
3.14.4 while the venv was on 3.14.6. It is pinned in `[tool.briefcase.app.retina.windows]`:

```toml
support_revision = "6"
```

That number also governs **OpenSSL**: `libssl-3.dll` and `libcrypto-3.dll` come from the *same*
zip as `python314.dll`, and CPython 3.14.6 is built against OpenSSL 3.5.7 (the LTS branch) whereas
3.14.5 was still on 3.0.20. So this is the single line to move at the next Python *or* OpenSSL
CVE, and the only place in the repository where that runtime's version is written (it is not in
`credits.json`).

Three traps:

1. **Briefcase does not re-download while `build/retina/windows/` exists.** Delete it before
   `briefcase create windows`, otherwise moving the number changes *nothing* and the MSI looks
   fixed without being so.
2. **The generated `briefcase.toml` keeps displaying the template's `support_revision`.** That is
   normal — the pin wins at download time, not in that file. The authoritative check is the
   `ProductVersion` of the DLLs in `build/retina/windows/app/src/`.
3. **Windows only.** Elsewhere the support package is a BeeWare artifact
   (`…-support.b<N>.tar.gz`) whose revision is nothing like a python.org micro version; putting
   `"6"` there would break Linux and macOS.

The URL built is `python.org/ftp/python/3.14.6/python-3.14.6-embed-amd64.zip`: the `3.14` comes
from the Python *running* briefcase, the `6` from the pin. Keep the development venv on the same
minor.

### Offline plate solving

On **Windows**, `PlateSolve` (backend `auto`) uses **ASTAP**, because the `astrometry` Python
package does not compile under MSVC. On Linux and macOS it keeps the `astrometry` backend. ASTAP
(executable plus the D05 database, ~105 MB, MPL 2.0) is fetched by `scripts/fetch_astap.py` into
`vendor/astap/` (outside the repository) and bundled through the `sources` entry of
`[tool.briefcase.app.retina.windows]`.

The pure-Python offline solver downloads the astrometry.net index files once, into
`~/.cache/retina/astrometry-indexes`.

---

## 16. Hard-won details

Traps that cost real debugging time. They look arbitrary until they bite.

**The WebView2 profile must go to `%LOCALAPPDATA%\Retina2\webview`** (`retina_shell::profile_dir`).
By default wry writes it to `<exe>.WebView2/`, next to the binary — and under `C:\Program Files\`
that directory is not writable, so the window simply never opens.

**A Monaco `editor.addCommand` is global.** It registers into the keybinding service **shared by
every editor**, not on the instance. Without a context key as third argument, the console prompt's
Enter binding made it impossible to insert a newline in a script editor. Every `addCommand` must
carry its own context key.

**The window edges are not natively grabbable.** The window is created undecorated (the title bar
is drawn by the frontend), and WebView2 creates child HWNDs covering the whole client area, so
`WM_NCHITTEST` never reaches the parent. The frontend therefore lays down eight CSS handles that
call back into `window_resize` (`web/src/shell/WindowResizeHandles.tsx`). Accepted losses: Windows
11 Snap Layouts, Alt+Space, and the taskbar's "Move / Size" entry. `with_undecorated_shadow(true)`
restores the drop shadow, Aero Snap and the minimize animation — without it the window looks flat.

**`PrintWindow` returns truncated captures of a WebView2 window** — composed layers missing, DPI
ignored. Do not draw conclusions from one. To see the real DOM, set
`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` and attach with
`chromium.connectOverCDP`.

**A pixel URL is not immutable across runs.** View identifiers (`Image01`…) *and* generations both
restart at 1 on every launch, so `/api/pixels/Image01.f16?gen=1` designates a different image in
every session. Serving it as `immutable` was a lie, and the WebView2 disk cache — which survives
restarts — replayed the previous session's pixels: `texImage2D` failed ("ArrayBufferView not big
enough") and **the viewport stayed black**; worse, at equal dimensions the upload succeeded and the
screen silently showed another image's pixels. Responses are now revalidated (`no-cache`) against
an `ETag` prefixed by a per-run `RUN_ID`.

**The Qt shell was removed** (July 2026): it duplicated the web shell, which covers its entire
scope. If a comment or a document still mentions PySide6, that is residue to fix, not a target.
