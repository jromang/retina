# Retina

**Open-source astrophotography image processing, fully scriptable in Python.**

Retina calibrates, registers, integrates and processes astronomical images. Its core is a
Python library that runs headless; the interface is one of its clients, not its owner.

![Retina processing M51](assets/screenshot.jpg)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![141 processes](https://img.shields.io/badge/processes-141-green)

## The founding principle

**Everything is reachable from the built-in Python console.** Opening and saving, creating a
window or a preview, choosing the active view, applying a process, managing masks and history,
arranging the docks, running a batch — all of it goes through the `retina` API. No feature is
reserved for the interface.

Better: **every gesture in the interface prints the equivalent Python**, executable and
copyable. You can see it in the console at the bottom of the screenshot above:

```python
# ← GUI: app.open('C:\\Users\\jroma\\Desktop\\h_m51_b_s05_drz_sci.fits')
# ← GUI: app.set_viewport((4300, 6100), zoom=0.0404918)
# ← GUI: app.layout.open_process('AIDeconvolution')
```

You learn the API by clicking, and any sequence of clicks becomes a script.

## What it does

- **141 processes** — calibration, cosmetic correction, debayer, registration, integration,
  background extraction, deconvolution, denoising, stretching, colour calibration, star
  removal, photometry, astrometry, mosaics, HDR.
- **Automated pre-processing** (`retina.pipeline`) — point it at a folder of raw frames and it
  scans, groups, builds masters, calibrates, registers and integrates, with caching and resume.
- **Inspection and comparison** — frame selector, blink, linked views, before/after curtain,
  FITS header.
- **Interactive tools** — masks composited in the shader, handle-driven crop, clone stamp,
  click-to-measure PSF, manual pair registration, celestial readout.
- **Script mode** — a full-page Monaco editor with hover and signature help from the embedded
  IPython, plus a `Script` process that makes a script run undoable and replayable.
- **Projects** — a `.retina` file stores an entire session, undo history included.
- **Bilingual** — English by default, complete French, detected at startup.

## Install

**Prerequisites**: Python ≥ 3.11, a [Rust toolchain](https://rustup.rs/), Node ≥ 20.

```bash
git clone https://github.com/jromang/retina && cd retina
python -m venv .venv && source .venv/bin/activate
pip install maturin
pip install -e '.[web,xisf,astro,project,dev]'

# Build the native core.
maturin develop --release

# Build the frontend into the Python package.
cd web && npm install && npm run build && cd ..

python -m retina.web          # server + native window
```

Optional GPU acceleration (Linux and Windows only — the CuPy wheel is tied to a CUDA branch,
which is why it cannot go in the line above):

```bash
pip install -e '.[cuda]'      # CUDA 13; use '.[cuda12]' for a CUDA 12 driver
```

Without any interface, in pure script form:

```bash
python -m retina.run recipe.py        # no graphical dependency
python -m retina.pipeline /data/M31   # automated pre-processing, headless
```

### Windows installer

Each release ships an MSI, published on the
[releases page](https://github.com/jromang/retina/releases).

The installer is **not code-signed**, so Windows SmartScreen will warn on first run: choose
*More info* → *Run anyway*. Verify your download against the `SHA256SUMS.txt` published beside
it — noting that MSI packaging is not bit-for-bit reproducible, since WiX embeds timestamps and
generated GUIDs, so a checksum identifies an artifact rather than a version.

Every release is built by a public workflow
([`release-windows.yml`](.github/workflows/release-windows.yml)) from the source of this
repository, with public logs: nothing is built on a developer machine and uploaded by hand.

What the software does with your data: [PRIVACY.md](PRIVACY.md). In short, it will not transfer
any information to other networked systems unless you ask it to.

## Running the tests

```bash
pytest -q -m "not gpu"                     # Python: domain + server, headless
ruff check python tests scripts
cd web && npm test                         # vitest
cd web && npx playwright test              # end-to-end, through a real browser
```

The suite self-skips what is not installed, so install the extras above if you want it to
mean something.

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — the design: the four non-negotiables, the three
  layers, the object model, the pre-processing engine, the web shell, GPU dispatch, packaging,
  and the traps worth knowing before you touch any of it.
- Per-process reference documentation ships with the application (help panel), in English and
  French, under [`python/retina/resources/doc/`](python/retina/resources/doc/).

## Contributing

Issues and pull requests are welcome. Read
[ARCHITECTURE.md](ARCHITECTURE.md) first — in particular the console/GUI parity rule, which is
the constraint most likely to make a patch need rework: any capability added to the interface
must exist in the scriptable API first.

Source code, comments and commit messages are in English. French exists in the product
catalogues only, and `python scripts/check_english.py` enforces the boundary.

## Licence

[GPL-3.0-or-later](LICENSE).

Retina bundles third-party components; `app.credits()` in the console, or **Help → Licences**
in the interface, lists every one with its licence. One caveat worth stating up front: the
optional **GraXpert AI models** are CC BY-NC-SA 4.0 — free to use, but **commercial use is
prohibited**. That restriction comes from the models, not from Retina, which restricts nothing.

---

*[Version française du README](README.fr.md)*
