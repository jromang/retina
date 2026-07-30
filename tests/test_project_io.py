"""The ``.retina`` project format — the full round trip, headless.

The central test of the whole project-file work: a rich session (two windows, a frozen and a
volatile preview, a shared mask, a history with redo left in reserve, STF, WCS, keywords,
viewport, linked views) written out and read back into a **fresh application** must return
exactly the same thing — undo and redo included, the way projects that embed their swap files
do.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytest.importorskip("h5py")
pytest.importorskip("astropy")

from retina import STF, ChannelSTF, Image
from retina.app import Application
from retina.io.project import (
    PROJECT_SUFFIX,
    estimate_size,
    load_project,
    read_documents,
    save_project,
)
from retina.model.window import ImageWindow
from retina.process.registry import load_builtin
from retina.process.unknown import UnknownProcess

load_builtin()


def _h5py():
    """Local import: the project module itself only pulls h5py in when called."""
    import h5py

    return h5py


def _image(h: int = 12, w: int = 10, c: int = 1, seed: int = 0) -> Image:
    rng = np.random.default_rng(seed)
    return Image(rng.random((h, w, c)).astype(np.float32))


def _synthetic_wcs():
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [5.0, 6.0]
    wcs.wcs.cdelt = [-0.001, 0.001]
    wcs.wcs.crval = [10.684, 41.269]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def _rich_session() -> Application:
    """Two windows, and just about everything a session can carry."""
    from astropy.io import fits
    from retina.processes.channels import Invert, Rescale

    app = Application()
    win = app.new_window(_image(seed=1), window_id="Image01", file_path="/data/m31.fits")
    other = app.new_window(_image(seed=2), window_id="Image02")

    # Three processes on the main view, then one undo: some redo is left in reserve.
    Invert().execute_on(win.main_view)
    Rescale().execute_on(win.main_view)
    Invert().execute_on(win.main_view)
    win.main_view.undo()

    # A frozen preview with its own history, and a volatile one.
    frozen = win.create_preview(1, 2, 6, 8, preview_id="Image01_Frozen")
    frozen.store()
    Invert().execute_on(frozen)
    win.create_preview(0, 0, 4, 4, preview_id="Image01_Volatile")

    # Mask borrowed from the second window: object sharing must survive.
    app.set_mask(other.main_view.id, window=win)
    win.mask_inverted = True

    win.keywords = {
        "EXPTIME": 300.0,
        "FILTER": "Ha",
        "XBINNING": 2,
        "SIMPLE": True,
        "OBSERVER": fits.card.Undefined(),
    }
    win.wcs = _synthetic_wcs()
    win.main_view.stf = STF([ChannelSTF(0.01, 0.3, 0.9)])
    win.viewport.set_viewport((3.5, 4.5), zoom=8.0)
    win.viewport.set_display_channel("cie_a")
    win.viewport.set_mask_visible(False)
    win.set_current_view(frozen)

    app.link_viewports()
    app.set_active_window(other)
    return app


# --- the round trip --------------------------------------------------------------------

def test_full_round_trip(tmp_path):
    app = _rich_session()
    path = str(tmp_path / "project.retina")
    before = {
        "labels": app.windows[0].main_view.history_labels(),
        "index": app.windows[0].main_view.history_index,
        "pixels": [e.image.data.copy()
                   for e in app.windows[0].main_view.history_entries()],
        "viewport": app.windows[0].viewport.to_dict(),
        "stf": app.windows[0].main_view.stf.to_dict(),
        "wcs": app.windows[0].wcs.to_header(relax=True).tostring(),
    }

    save_project(app, path)

    fresh = Application()
    report = load_project(fresh, path)

    assert report.windows == ["Image01", "Image02"]
    assert [w.id for w in fresh.windows] == ["Image01", "Image02"]
    assert fresh.active_window.id == "Image02"
    assert fresh.linked_viewports() == ["Image01", "Image02"]

    win = fresh.windows[0]
    assert win.file_path == "/data/m31.fits"
    # history: same labels, same index, same pixels state by state
    assert win.main_view.history_labels() == before["labels"]
    assert win.main_view.history_index == before["index"]
    for expected, entry in zip(before["pixels"], win.main_view.history_entries(), strict=True):
        assert np.array_equal(expected, entry.image.data)
    # undo/redo intact: that is the whole point of embedding the states
    assert win.main_view.can_go_forward and win.main_view.can_go_backward
    assert win.main_view.redo() is True
    assert win.main_view.undo() is True
    assert np.array_equal(win.main_view.image.data, before["pixels"][before["index"]])

    assert win.main_view.stf.to_dict() == before["stf"]
    assert win.viewport.to_dict() == before["viewport"]
    assert win.wcs.to_header(relax=True).tostring() == before["wcs"]
    assert win.current_view.id == "Image01_Frozen"


def test_previews_keep_their_rect_state_and_volatility(tmp_path):
    app = _rich_session()
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    fresh = Application()
    load_project(fresh, path)

    win = fresh.windows[0]
    frozen = win.preview_by_id("Image01_Frozen")
    volatile = win.preview_by_id("Image01_Volatile")
    assert frozen.rect == (1, 2, 6, 8)
    assert frozen.volatile is False
    assert frozen.history_labels() == ["initial", "Invert"]
    assert volatile.rect == (0, 0, 4, 4)
    assert volatile.volatile is True


def test_a_volatile_preview_still_restarts_from_the_base_after_reload(tmp_path):
    """Volatility is a behaviour, not a decorative flag: after reloading, a process on the
    preview must still re-cut from the main view.

    A dedicated session, without a mask: the mask belongs to the window and its geometry is
    that of the main view, so processing a smaller preview already raises — a deliberate
    divergence from the alternative of cropping the mask to the preview rectangle, and one
    that has nothing to do with what this test checks."""
    from retina.processes.channels import Invert

    app = Application()
    win = app.new_window(_image(seed=3), window_id="Image01")
    win.create_preview(0, 0, 4, 4, preview_id="Image01_Volatile")
    path = str(tmp_path / "p.retina")
    save_project(app, path)
    fresh = Application()
    load_project(fresh, path)
    win = fresh.windows[0]
    volatile = win.preview_by_id("Image01_Volatile")

    Invert().execute_on(volatile)

    assert volatile.history_labels() == ["initial", "Invert"]
    x0, y0, x1, y1 = volatile.rect
    base = win.main_view.image.data[y0:y1, x0:x1, :]
    assert np.allclose(volatile.history_entries()[0].image.data, base)


def test_the_mask_survives_with_its_flags_and_its_sharing(tmp_path):
    app = _rich_session()
    expected = app.windows[0].mask.data.copy()
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    fresh = Application()
    load_project(fresh, path)

    win, other = fresh.windows
    assert np.array_equal(win.mask.data, expected)
    assert win.mask_inverted is True
    assert win.mask_enabled is True
    # The mask IS the other window's image: deduplication restores the object sharing,
    # otherwise a project with ten masked views would weigh ten times its pixels.
    assert win.mask.data is other.main_view.image.data


def test_the_fits_keywords_survive_types_included(tmp_path):
    from astropy.io import fits

    app = _rich_session()
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    fresh = Application()
    load_project(fresh, path)

    kw = fresh.windows[0].keywords
    assert kw["EXPTIME"] == pytest.approx(300.0) and isinstance(kw["EXPTIME"], float)
    assert kw["FILTER"] == "Ha"
    assert kw["XBINNING"] == 2 and isinstance(kw["XBINNING"], int)
    assert kw["SIMPLE"] is True
    # A keyword present WITHOUT a value is a common case in FITS; turning it into `null`
    # silently would read back as an empty string, hence as an invented value.
    assert isinstance(kw["OBSERVER"], fits.card.Undefined)


def test_a_project_without_astrometry_does_not_fabricate_a_wcs(tmp_path):
    app = Application()
    app.new_window(_image(), window_id="Lone01")
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    fresh = Application()
    load_project(fresh, path)

    assert fresh.windows[0].wcs is None
    assert fresh.windows[0].has_astrometric_solution is False


# --- deduplication and volume ------------------------------------------------------------

def test_shared_pixels_are_written_only_once(tmp_path):
    """A view's current image IS the image of its history entry, and the mask that of its
    source view. Without deduplication, a project would weigh several times its pixels."""
    app = _rich_session()
    path = str(tmp_path / "p.retina")

    summary = save_project(app, path)

    with _h5py().File(path, "r") as file:
        written = len(file["arrays"])
    assert written == summary["arrays"]
    # 4 states on Image01 (initial + 3 processes), 2 on the frozen preview, 1 on the volatile
    # one, 1 for Image02 — the mask and the current images are shares.
    assert written == 8


def test_estimate_size_counts_unique_arrays():
    """The sum of the **unique** arrays, not of the references: two views over the same
    pixels only cost once."""
    app = _rich_session()
    full = 12 * 10 * 4             # main view 12×10, float32
    frozen = (6 - 1) * (8 - 2) * 4  # frozen preview: rect (x0,y0,x1,y1) = (1,2,6,8) → 5×6
    volatile = 4 * 4 * 4

    # 4 states on Image01 + 2 on the frozen preview + 1 on the volatile one + 1 for Image02.
    expected = 4 * full + 2 * frozen + volatile + full

    assert estimate_size(app) == expected


# --- counters and uniqueness -------------------------------------------------------------

def test_the_window_counter_is_realigned(tmp_path):
    """`ImageWindow._counter` is a class variable: without realignment, the first window
    created after opening would reuse an identifier that is already taken, and the global
    pixel addressing would designate two views at once."""
    app = Application()
    app.new_window(_image(), window_id="Image07")
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    fresh = Application()
    ImageWindow._counter = 0
    load_project(fresh, path)
    created = fresh.new_window(_image())

    assert created.id != "Image07"
    assert {w.id for w in fresh.windows} == {"Image07", created.id}


def test_a_project_with_duplicate_identifiers_is_refused_without_touching_anything(tmp_path):
    app = Application()
    app.new_window(_image(), window_id="Dupe01")
    path = str(tmp_path / "p.retina")
    save_project(app, path)
    # sabotage the manifest: two windows with the same name
    with _h5py().File(path, "r+") as file:
        manifest = json.loads(file["manifest"][()])
        manifest["windows"].append(dict(manifest["windows"][0]))
        del file["manifest"]
        file.create_dataset("manifest", data=json.dumps(manifest),
                               dtype=_h5py().string_dtype("utf-8"))

    fresh = Application()
    control = fresh.new_window(_image(), window_id="Control01")
    with pytest.raises(ValueError, match="Duplicate"):
        load_project(fresh, path)

    assert fresh.windows == [control]  # nothing moved


# --- unknown process --------------------------------------------------------------------

def test_a_missing_process_becomes_a_placeholder_and_is_rewritten_intact(tmp_path,
                                                                        monkeypatch):
    """The `UnknownProcess` rule: a missing plugin must not prevent the project from being
    opened, nor make the settings of that step be lost.

    The missing plugin is simulated as faithfully as possible: we drop the registry entry
    **and** neutralise `load_builtin`, which `registry.get` would otherwise call back to
    reimport everything — which would resurrect the process and make the test vacuous."""
    from retina.process import registry
    from retina.processes.channels import Rescale

    app = Application()
    win = app.new_window(_image(), window_id="Image01")
    Rescale(low=0.25, high=0.75).execute_on(win.main_view)
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    removed = registry._REGISTRY.pop("Rescale")
    monkeypatch.setattr(registry, "load_builtin", lambda: None)
    try:
        fresh = Application()
        report = load_project(fresh, path)

        assert report.unknown_processes == ["Rescale"]
        step = fresh.windows[0].main_view.history_entries()[1].process
        assert isinstance(step, UnknownProcess)
        with pytest.raises(RuntimeError, match="Rescale"):
            step.execute_on(fresh.windows[0].main_view)

        # rewritten on the machine that lacks the process, then read back where it exists
        path2 = str(tmp_path / "p2.retina")
        save_project(fresh, path2)
    finally:
        registry._REGISTRY["Rescale"] = removed

    restored = Application()
    report2 = load_project(restored, path2)
    assert report2.unknown_processes == []
    replayed = restored.windows[0].main_view.history_entries()[1].process
    assert replayed.process_id == "Rescale"
    # The settings crossed the machine that lacked the process: a temporary absence must not
    # become a permanent loss.
    assert replayed.low == pytest.approx(0.25) and replayed.high == pytest.approx(0.75)


# --- moved / modified scripts -------------------------------------------------------------

def _project_with_script(tmp_path, script_path) -> str:
    from retina.processes.script import Script, file_digest

    app = Application()
    win = app.new_window(_image(), window_id="Image01")
    instance = Script(path=str(script_path), values="{}",
                      digest=file_digest(str(script_path)))
    win.main_view.begin_process("Script", process=instance)
    win.main_view.end_process()
    path = str(tmp_path / "p.retina")
    save_project(app, path)
    return path


def test_a_modified_script_is_reported_on_opening(tmp_path):
    """The `Script` process only said so at **replay** time, through a print. Opening is
    still the moment when the user can go and find the right file."""
    script = tmp_path / "recipe.py"
    script.write_text("print('v1')\n")
    project = _project_with_script(tmp_path, script)
    script.write_text("print('v2 — modified since')\n")

    report = load_project(Application(), project)

    assert report.scripts_changed == [str(script)]
    assert report.scripts_missing == []


def test_a_vanished_script_is_reported_on_opening(tmp_path):
    script = tmp_path / "recipe.py"
    script.write_text("print('v1')\n")
    project = _project_with_script(tmp_path, script)
    script.unlink()

    report = load_project(Application(), project)

    assert report.scripts_missing == [str(script)]
    assert report.scripts_changed == []


# --- document blob (opaque) ----------------------------------------------------------------

def test_the_document_blob_travels_without_being_interpreted(tmp_path):
    app = Application()
    app.new_window(_image(), window_id="Image01")
    path = str(tmp_path / "p.retina")
    blob = {"version": 1, "scripts": {"docs": [{"id": "script:1", "text": "x = 1"}]}}

    save_project(app, path, documents=blob)

    assert read_documents(path) == blob
    assert load_project(Application(), path).documents == blob


def test_a_project_without_documents_returns_none(tmp_path):
    app = Application()
    app.new_window(_image(), window_id="Image01")
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    assert read_documents(path) is None
    assert load_project(Application(), path).documents is None


# --- robustness of the format ---------------------------------------------------------------

def test_the_suffix_is_added_if_it_is_missing(tmp_path):
    app = Application()
    app.new_window(_image(), window_id="Image01")

    summary = save_project(app, str(tmp_path / "no_suffix"))

    assert summary["path"].endswith(PROJECT_SUFFIX)
    assert (tmp_path / f"no_suffix{PROJECT_SUFFIX}").exists()


def test_the_write_is_atomic(tmp_path, monkeypatch):
    """An interruption must never leave a truncated `.retina` that a later open would
    believe to be valid."""
    import retina.io.project as project

    app = Application()
    app.new_window(_image(), window_id="Image01")
    path = tmp_path / "p.retina"

    def _blow_up(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(project, "_write_array", _blow_up)
    with pytest.raises(OSError):
        save_project(app, str(path))

    assert not path.exists()
    assert not (tmp_path / "p.retina.part").exists()


def test_a_file_that_is_not_a_project_is_refused(tmp_path):
    other = tmp_path / "other.retina"
    with _h5py().File(other, "w") as file:
        file.create_dataset("data", data=np.zeros(4))

    with pytest.raises(ValueError, match="not a Retina project"):
        load_project(Application(), str(other))


def test_a_future_version_is_refused_with_a_useful_message(tmp_path):
    app = Application()
    app.new_window(_image(), window_id="Image01")
    path = str(tmp_path / "p.retina")
    save_project(app, path)
    with _h5py().File(path, "r+") as file:
        file.attrs["version"] = 99

    with pytest.raises(ValueError, match="Update Retina"):
        load_project(Application(), path)


def test_progress_is_reported_and_cancellable(tmp_path):
    """A heavy project is written inside a job: without checkpoints it would be neither
    tracked nor interruptible."""
    from retina.process import context
    from retina.process.progress import ProcessCancelled, ProgressMonitor

    app = _rich_session()
    fractions: list[float] = []

    class _Monitor(ProgressMonitor):
        def report(self, fraction, message=""):
            fractions.append(fraction)
            super().report(fraction, message)

    monitor = _Monitor()
    context.set_monitor(monitor)
    try:
        save_project(app, str(tmp_path / "p.retina"))
        assert len(fractions) > 1 and fractions[-1] == 1.0

        monitor.cancel()
        with pytest.raises(ProcessCancelled):
            save_project(app, str(tmp_path / "cancelled.retina"))
    finally:
        context.set_monitor(None)

    assert not (tmp_path / "cancelled.retina").exists()


def test_the_format_is_readable_by_any_hdf5_tool(tmp_path):
    """No external filter: a project must open with bare h5py, without any plugin."""
    app = _rich_session()
    path = str(tmp_path / "p.retina")
    save_project(app, path)

    with _h5py().File(path, "r") as file:
        assert file.attrs["format"] == "retina-project"
        assert json.loads(file["manifest"][()])["version"] == 1
        first = file["arrays"]["a000000"]
        assert first.compression == "gzip"
        assert first.shuffle is True
        assert first.fletcher32 is True
        assert np.asarray(first[()]).dtype == np.float32


# --- guard against serialiser drift ----------------------------------------------------------

def test_no_window_attribute_is_forgotten_silently():
    """An attribute added tomorrow to `ImageWindow` must make a test fail, not vanish
    silently from projects. The list below is the contract: we add to it what we serialise,
    and we justify what we leave out."""
    from retina.io.project import _ArrayStore, _window_to_dict

    app = Application()
    win = app.new_window(_image(), window_id="Image01")

    actual = {name for name in vars(win) if not name.startswith("__")}
    serialised = set(_window_to_dict(win, _ArrayStore()))
    #: Left out knowingly, with the reason why.
    ignored = {
        "_main_view",   # serialised under "main_view"
        "_previews",    # serialised under "previews"
        "_current_view",  # serialised under "current_view" (an identifier, not the object)
        "mask_enabled",   # inside the "mask" sub-dict
        "mask_inverted",  # same
        "mask_source_id",  # same, under "source" — the id of the view the mask comes from
    }

    forgotten = actual - serialised - ignored
    assert not forgotten, (
        f"ImageWindow attributes not serialised: {sorted(forgotten)}. "
        "Add them to _window_to_dict/_window_from_dict, or to this test's `ignored` "
        "list with the reason."
    )
