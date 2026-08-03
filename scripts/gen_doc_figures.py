#!/usr/bin/env python
"""Generate the documentation figures — by running Retina on real data.

A **deliberate** act, like ``gen_process_docs.py`` or ``gen_web_fixtures.py``: nothing runs it
automatically, and running it is a decision (it rewrites versioned binaries).

The reference documentation was, until now, 286 pages without a single image, on a subject
where the whole point of a process is *what it does to the picture*. The obvious fix — take
screenshots — has a defect that only shows up months later: a screenshot is a claim about the
code that nothing keeps true. So the figures are **produced by the code they illustrate**,
through the public API, and can be regenerated at any time:

    python scripts/gen_doc_figures.py                 # every declared figure
    python scripts/gen_doc_figures.py Deconvolution   # one process
    python scripts/gen_doc_figures.py --list          # what is declared, and its weight

# Declaring figures

One module per process, ``scripts/doc_figures/<ProcessId>.py``, exporting ``figures(ctx)``.
The module is plain Python written against ``retina.*`` — **not** a declarative schema. A
YAML "source / params / crop" format was the first idea and was dropped: the second process
needs a mask, the third a two-step chain, the fourth a composition of three views, and the
schema becomes an expression language nobody asked for (the repository already refuses home
grown DSLs). A Python function has all of that for free, and doubles as an executable example
of the API.

The context gives what every such module needs — sources, framing, display stretch, writing —
so a module stays three lines long when the figure is simple.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import retina  # noqa: E402
from _console import configure as _configure_console  # noqa: E402
from retina import documentation as D  # noqa: E402

SPEC_DIR = Path(__file__).resolve().parent / "doc_figures"

#: Written width. Wider buys nothing: the viewer's column is 860 px, and the reader compares
#: two images side by side, so each one is shown at half that.
WIDTH = 900
#: WebP quality. Measured on this corpus: 82 keeps star profiles and background grain
#: readable at a third of the weight of 95, and the artefacts of 70 look like a denoising
#: defect — which, in a page about denoising, would be a lie.
QUALITY = 82
#: Per-image ceiling, enforced here *and* by ``tests/test_docs.py``: the docs ship inside the
#: wheel, and PixInsight's 184 MB of documentation is the cautionary tale.
MAX_BYTES = 200 * 1024
#: Below this standard deviation an image carries no structure — a black rectangle, a uniform
#: grey. Calibrated on the first tranche, whose weakest legitimate figure (a star mask, mostly
#: background) sits at 0.09.
FLAT_STD = 0.012
#: Below this mean absolute difference, a before/after pair is two copies of one picture as far
#: as a reader is concerned. The first tranche's subtlest honest pair (a background extraction
#: on a mild real gradient) sits at 0.014.
PAIR_DELTA = 0.006

#: In-repo sources. Deliberately small and versioned: a figure must be regenerable on a
#: checkout, offline, without downloading 162 MB first.
#: Both are mono, and that is the whole of what the repository offers: the only RGB frame it
#: carries is an annotation-test fixture with catalogue rings drawn on it. Colour figures go
#: through :meth:`FigureContext.survey` instead.
SOURCES = {
    "starfield": ROOT / "sample_starfield.fits",   # mono, linear, dense star field
    "field": ROOT / "data" / "real_field.fits",     # mono, real sky, real gradient
}


class FigureContext:
    """What a figure module is handed: sources, framing, display stretch, writing."""

    def __init__(self, process_id: str, *, dry_run: bool = False) -> None:
        self.process_id = process_id
        self.dry_run = dry_run
        self.written: list[tuple[Path, int]] = []
        self._stats: list[tuple[str, np.ndarray, bool]] = []
        self._dir = D.doc_dir(process_id) / "figures"

    # --- sources ----------------------------------------------------------- #
    def load(self, name: str) -> retina.Image:
        """One of the in-repo sources (see :data:`SOURCES`), as an :class:`Image`."""
        from retina.io.fits import load_fits

        path = SOURCES.get(name)
        if path is None:
            raise KeyError(f"unknown source {name!r}; known: {sorted(SOURCES)}")
        return load_fits(str(path))[0]

    def survey(
        self,
        ra: float = 202.4696,
        dec: float = 47.1952,
        *,
        fov: float = 0.25,
        size: int = 900,
        bands: tuple[str, str, str] = ("panstarrs-i", "panstarrs-r", "panstarrs-g"),
        balanced: bool = True,
    ) -> retina.Image:
        """A colour frame built from three HiPS bands (default: M51 in Pan-STARRS i/r/g).

        The repository has **no clean RGB source**. Its only colour frame,
        ``data/pleiades_annotated.fits``, carries burnt-in catalogue circles and magnitude
        labels — it is a fixture for the annotation tests, and the figures first made from it
        showed a sky covered in yellow rings. Synthesising colour from a mono frame was the
        other option, and it would have meant illustrating a colour process with a colour no
        telescope produced.

        So the colour source is the sky itself, through ``hips2fits`` — the same service
        ``SurveyReference`` uses, with the same cache. The consequence to accept: the colour
        figures need the network the first time they are generated, where the mono ones never
        do.

        M51 rather than the Pleiades, which was the first try: at this depth Pan-STARRS
        saturates bright stars, and the cluster came back with black holes where its seven
        sisters should be. And the colour is deliberately **not** calibrated — each band is
        merely put on a common black and white point, which is what an uncalibrated composite
        looks like. That is a feature for these pages: the cast the figures show is real, so
        ``SCNR`` illustrates itself on a genuine defect rather than on one staged for the
        picture.

        ``balanced=False`` skips even that common black point and hands back the three bands
        on the scales the survey served them, sky levels and all. It is the state a colour
        composite is genuinely in before anyone has touched it, and the only honest source for
        the pages about *reaching* neutrality — with the balancing in place,
        ``BackgroundNeutralization`` had nothing left to correct and its before/after pair was
        two copies of one picture (mean |Δ| 0.0028, caught by :meth:`review`).
        """
        from astropy.wcs import WCS
        from retina import hips

        wcs = WCS(naxis=2)
        wcs.wcs.crpix = [size / 2, size / 2]
        wcs.wcs.cdelt = [-fov / size, fov / size]
        wcs.wcs.crval = [ra, dec]
        wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        planes = []
        for band in bands:
            plane = np.nan_to_num(hips.fetch(wcs, (size, size), band, max_size=size)[0], nan=0.0)
            if balanced:
                # Common black and white point. `hips.fetch` normalises each band on its own
                # percentiles, so without this the three arrive at unrelated scales and the
                # composite is whatever the faintest band decides.
                low, high = float(np.median(plane)), float(np.percentile(plane, 99.7))
                plane = (plane - low) / max(high - low, 1e-6)
            planes.append(plane)
        data = np.stack(planes, axis=-1)
        if balanced:
            data = data * 0.85 + 0.03
        return retina.Image(np.clip(data, 0.0, 1.0).astype("float32"))

    def survey_view(self, **kwargs):
        """The same colour frame, but **plate-solved and open in a window**.

        Some processes need the sky coordinates rather than the pixels: a coordinate grid, a
        catalogue overlay, a finding chart, a survey reference. They read the WCS from the
        *view*, which an :class:`Image` does not carry — so the composite is written to a
        temporary FITS with its WCS keywords and reopened through the ordinary
        ``app.open``. That is the user's own path, not a private one: whatever works here
        works on their solved file.
        """
        import tempfile

        from astropy.wcs import WCS
        from retina.io.fits import save_fits, wcs_keywords

        size = int(kwargs.get("size", 900))
        fov = float(kwargs.get("fov", 0.25))
        ra = float(kwargs.get("ra", 202.4696))
        dec = float(kwargs.get("dec", 47.1952))
        wcs = WCS(naxis=2)
        wcs.wcs.crpix = [size / 2, size / 2]
        wcs.wcs.cdelt = [-fov / size, fov / size]
        wcs.wcs.crval = [ra, dec]
        wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

        image = self.survey(**kwargs)
        path = Path(tempfile.gettempdir()) / f"retina_doc_{self.process_id}.fits"
        save_fits(str(path), image, wcs_keywords(wcs))
        window = retina.app.open(str(path))
        retina.app.set_active_window(window)
        return window.main_view

    def sample(self, sample_id: str) -> Path:
        """Folder of a downloadable sample dataset (``retina.samples``), fetched if needed.

        For the calibration processes, which need genuine bias/dark/flat frames that no
        synthetic array can stand in for. Everything else uses :meth:`load`, so the common
        case stays offline.
        """
        from retina import samples

        return Path(samples.ensure(sample_id))

    # --- framing and display ------------------------------------------------ #
    @staticmethod
    def crop(image, y: int, x: int, height: int, width: int):
        """A window into an image — a full frame at 900 px shows nothing at the pixel scale.

        Accepts and returns the same kind of object (``Image`` or ndarray), so it composes
        both before and after a process.
        """
        data = image if isinstance(image, np.ndarray) else image.data
        out = data[y : y + height, x : x + width]
        return out if isinstance(image, np.ndarray) else image.with_data(out)

    @staticmethod
    def autostretch(image, *, reference=None):
        """Apply the auto-STF, for display only — the same one the viewport computes.

        A linear astronomical image is black on screen: printed as is, every figure in the
        documentation would be a black rectangle. ``reference`` forces the stretch of another
        image, which is what a before/after pair needs — computing one stretch per image would
        renormalise the very difference the pair exists to show.
        """
        from retina.model.stf import STF

        source = reference if reference is not None else image
        if not isinstance(source, retina.Image):
            source = retina.Image(np.asarray(source, dtype="float32"))
        return STF.auto_from_image(source).apply(image)

    # --- writing ------------------------------------------------------------ #
    def save(self, name: str, image, *, flat_on_purpose: bool = False) -> Path:
        """Write ``figures/<name>.webp`` next to the page's Markdown.

        ``flat_on_purpose`` waives the "this image shows nothing" check — see
        :meth:`review`. It is true of exactly one recurring case, the linear frame a stretch
        page opens on, which is nearly black *because that is the point*.
        """
        from PIL import Image as PILImage

        data = image if isinstance(image, np.ndarray) else image.data
        data = np.asarray(data, dtype="float32")
        if data.ndim == 3 and data.shape[2] == 1:
            data = data[:, :, 0]
        elif data.ndim == 3 and data.shape[2] > 3:
            # Alpha, or an extra channel: a figure is a picture, three channels is what a
            # picture has.
            data = data[:, :, :3]
        pil = PILImage.fromarray((np.clip(data, 0.0, 1.0) * 255.0 + 0.5).astype("uint8"))
        if pil.width > WIDTH:
            height = round(pil.height * WIDTH / pil.width)
            pil = pil.resize((WIDTH, height), PILImage.LANCZOS)

        target = self._dir / f"{name}.webp"
        if not self.dry_run:
            self._dir.mkdir(parents=True, exist_ok=True)
            # Quality is the dial, and the ceiling is the constraint — not the other way
            # round. A noisy frame (added grain, a square-root stretch) compresses far worse
            # than a smooth one and overshot 200 kB at the nominal setting; cropping it to fit
            # would have changed what the figure shows in order to satisfy a file size.
            for quality in (QUALITY, 70, 60, 50, 40):
                pil.save(target, "WEBP", quality=quality, method=6)
                if target.stat().st_size <= MAX_BYTES:
                    break
        size = target.stat().st_size if target.is_file() else 0
        self.written.append((target, size))
        self._stats.append((name, np.asarray(pil, dtype="float32") / 255.0, flat_on_purpose))
        return target

    # --- self-review -------------------------------------------------------- #
    def review(self) -> list[str]:
        """What is wrong with the figures this spec just produced, in plain words.

        Judging a hundred pairs by eye does not scale, and the two ways a figure fails are
        both arithmetic. **Flat**: the image carries no structure — a black rectangle, a
        uniform grey — so there is nothing to look at. **Identical**: the two images of a
        pair differ by less than the eye resolves, so the page shows a process that appears
        to do nothing, which is worse than showing no figure at all.

        Both were met while writing the first tranche: a colour mask that selected an empty
        hue range, and a sharpening that returned a black frame (which turned out to be a
        real bug in the process, not in the figure). A gate would have named them in a
        second each.
        """
        problems = []
        for target, size in self.written:
            if size > MAX_BYTES:
                problems.append(
                    f"{target.stem}: {size / 1024:.0f} kB, over the ceiling even at the "
                    "lowest quality this writer will use")
        for name, array, waived in self._stats:
            if waived:
                continue
            if float(array.std()) < FLAT_STD:
                problems.append(f"{name}: flat (std {float(array.std()):.4f}) — nothing to see")
        if len(self._stats) == 2:
            (n1, a1, _), (n2, a2, _) = self._stats
            if a1.shape == a2.shape:
                delta = float(np.abs(a1 - a2).mean())
                if delta < PAIR_DELTA:
                    problems.append(
                        f"{n1} vs {n2}: near-identical (mean |Δ| {delta:.4f}) — "
                        "the pair shows nothing")
        return problems


def _spec_modules() -> dict[str, Path]:
    if not SPEC_DIR.is_dir():
        return {}
    return {
        p.stem: p
        for p in sorted(SPEC_DIR.glob("*.py"))
        if not p.name.startswith("_")
    }


def _run_spec(process_id: str, path: Path, *, dry_run: bool) -> FigureContext:
    spec = importlib.util.spec_from_file_location(f"doc_figures.{process_id}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "figures"):
        raise AttributeError(f"{path.name}: no figures(ctx) function")
    ctx = FigureContext(process_id, dry_run=dry_run)
    module.figures(ctx)
    return ctx


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("processes", nargs="*", help="process ids (default: all declared)")
    parser.add_argument("--list", action="store_true", help="list the declared figures only")
    args = parser.parse_args(argv)

    modules = _spec_modules()
    if not modules:
        print(f"no figure module under {SPEC_DIR}")
        return 0

    wanted = args.processes or sorted(modules)
    unknown = [pid for pid in wanted if pid not in modules]
    if unknown:
        print(f"no figure module for: {', '.join(unknown)}")
        return 2

    registry = retina.all_processes()
    total = 0
    failures = 0
    for pid in wanted:
        if pid not in registry:
            # A module named after a process that no longer exists produces images no page
            # can show. Say so rather than write them.
            print(f"  ! {pid}: unknown process — module is stale")
            failures += 1
            continue
        try:
            ctx = _run_spec(pid, modules[pid], dry_run=args.list)
        except Exception as exc:  # a broken spec must not abort the other 24
            print(f"  ! {pid}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        for target, size in ctx.written:
            total += size
            flag = "  ← OVER BUDGET" if size > MAX_BYTES else ""
            action = "would write" if args.list else "wrote"
            print(f"  {action} {target.relative_to(ROOT)} ({size / 1024:.0f} kB){flag}")
        for problem in ctx.review():
            print(f"  ! {pid}/{problem}")
            failures += 1

    print(f"\n{len(wanted)} process(es), {total / 1024:.0f} kB total"
          + (f", {failures} problem(s)" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
