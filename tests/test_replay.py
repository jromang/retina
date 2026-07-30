"""Non-destructive prototype — replaying a past step with different parameters.

This is the one genuine gap in the market: the established astro suites refuse layers on
principle, while Affinity and SetiAstro have them without the traceability. The infrastructure
was almost in place — every history entry already carries the instance that produced it — and
two things were missing: the mask in force at execution time, and the replay loop.

This file is the case file for the verdict: what works, and what refuses cleanly.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image
from retina.model.view import ReplayError
from retina.process.registry import all_processes

get = all_processes().__getitem__


@pytest.fixture
def view():
    rng = np.random.default_rng(4)
    app = Application()
    win = app.new_window(Image(rng.random((32, 48, 1)).astype(np.float32)), window_id="Target")
    return win.main_view


def _chain(view, sigma=2.0):
    """Three processes, one of them geometrically neutral and one invertible."""
    get("GaussianConvolution")(sigma=sigma).execute_on(view)
    get("Rescale")().execute_on(view)
    get("Invert")().execute_on(view)
    return view


# --- the heart of the prototype ----------------------------------------------------

def test_replaying_with_unchanged_values_is_bit_for_bit_faithful(view):
    """Without exact fidelity the rest is pointless: we could not tell the effect of a changed
    parameter from the drift of the replay itself."""
    _chain(view)
    before = view.image.data.copy()

    assert view.replay(1)

    np.testing.assert_array_equal(view.image.data, before)


def test_replaying_with_other_parameters_recomputes_everything_downstream(view):
    _chain(view, sigma=2.0)
    with_2 = view.image.data.copy()

    view.replay(1, {"sigma": 5.0})

    # The result has changed…
    assert not np.allclose(view.image.data, with_2)
    # …and it is exactly what redoing the chain by hand would give.
    app = Application()
    control = app.new_window(Image(view.history_entries()[0].image.data.copy())).main_view
    _chain(control, sigma=5.0)
    np.testing.assert_allclose(view.image.data, control.image.data, atol=1e-6)


def test_the_shape_of_the_history_is_preserved(view):
    _chain(view)
    labels_before = view.history_labels()
    index_before = view.history_index

    view.replay(1, {"sigma": 4.0})

    assert view.history_labels() == labels_before
    assert view.history_index == index_before
    assert view.can_go_backward and not view.can_go_forward


def test_the_edited_instance_replaces_the_old_one_in_the_history(view):
    """A replay must be **replayable in its turn**: the history carries the new values."""
    _chain(view, sigma=2.0)

    view.replay(1, {"sigma": 4.0})

    assert view.history_entries()[1].process.sigma == pytest.approx(4.0)
    assert view.recipe().processes[0].sigma == pytest.approx(4.0)


def test_undo_after_a_replay_gives_the_recomputed_upstream_state(view):
    _chain(view, sigma=2.0)
    view.replay(1, {"sigma": 6.0})

    view.undo()

    # The intermediate state was redone too: it is no longer the one from before the replay.
    expected = get("GaussianConvolution")(sigma=6.0)._apply(
        view.history_entries()[0].image.data)
    expected = get("Rescale")()._apply(expected)
    np.testing.assert_allclose(view.image.data, expected, atol=1e-6)


def test_editing_the_last_step_touches_only_that_step(view):
    _chain(view)
    intermediate = view.history_entries()[2].image.data.copy()

    view.replay(3)

    np.testing.assert_array_equal(view.history_entries()[2].image.data, intermediate)


# --- the mask: what was really missing ------------------------------------------------

def _with_mask(view, inverse=False):
    app = Application()
    mask = np.zeros((32, 48, 1), np.float32)
    mask[:, :24] = 1.0  # left half processed, right half protected
    mask_window = app.new_window(Image(mask), window_id="Mask")
    view.window.set_mask(mask_window.main_view.image, inverted=inverse, source_id="Mask")
    # The domain image provider resolves the mask view by its id, just like PixelMath.
    from retina.process import context

    context.set_image_provider(
        lambda name: mask_window.main_view.image if name == "Mask" else None)
    return mask_window


def test_the_applied_mask_is_recorded_in_the_entry(view):
    _with_mask(view)
    get("Invert")().execute_on(view)

    entry = view.history_entries()[1]
    assert entry.mask_id == "Mask"
    assert entry.mask_inverted is False


def test_the_replay_applies_the_mask_of_the_time_not_the_current_one(view):
    """The gap this closes: without a recorded mask, replaying would have used the window's
    mask as it stands *today*, and so returned a different result without saying so."""
    _with_mask(view)
    get("Invert")().execute_on(view)
    result = view.image.data.copy()

    view.window.remove_mask()  # the window's mask is removed after the fact
    view.replay(1)

    np.testing.assert_allclose(view.image.data, result, atol=1e-6)
    # And the mask really did play its part: the right half is untouched.
    origin = view.history_entries()[0].image.data
    np.testing.assert_allclose(view.image.data[:, 24:], origin[:, 24:], atol=1e-6)


def test_a_vanished_mask_refuses_the_replay(view):
    from retina.process import context

    _with_mask(view)
    get("Invert")().execute_on(view)
    context.set_image_provider(lambda name: None)  # the mask view has been closed

    with pytest.raises(ReplayError, match="no longer exists"):
        view.replay(1)


def test_without_a_mask_nothing_is_recorded(view):
    get("Invert")().execute_on(view)
    assert view.history_entries()[1].mask_id is None


# --- clean refusals: a replay fails entirely or not at all ----------------------------

def test_a_non_replayable_step_downstream_refuses_everything(view):
    """Atomicity: a half-done replay would leave the view in an indescribable state."""
    from retina.process.unknown import UnknownProcess

    _chain(view)
    before = view.image.data.copy()
    entries = view.history_entries()
    entries[2].process = UnknownProcess({"process_id": "FromElsewhere", "values": {}})
    view.restore_history(entries, view.history_index)

    with pytest.raises(ReplayError, match="does not have"):
        view.replay(1, {"sigma": 9.0})

    np.testing.assert_array_equal(view.image.data, before)  # history intact


def test_a_step_without_a_process_refuses(view):
    """This is the case of a state recorded outside a bracket, or of an old truncated project."""
    _chain(view)
    entries = view.history_entries()
    entries[2].process = None
    view.restore_history(entries, view.history_index)

    with pytest.raises(ReplayError, match="no replayable process"):
        view.replay(1)


def test_index_zero_is_not_replayable(view):
    """The initial state was produced by no process — there is nothing to replay."""
    _chain(view)
    with pytest.raises(ReplayError, match="Nothing to replay"):
        view.replay(0)


def test_an_out_of_range_index_refuses(view):
    _chain(view)
    with pytest.raises(ReplayError, match="Nothing to replay"):
        view.replay(99)


def test_a_rejected_value_leaves_the_history_intact(view):
    """`Process.__init__` validates; a replay that fails at construction must break nothing."""
    _chain(view)
    before = view.image.data.copy()

    with pytest.raises(Exception):
        view.replay(1, {"nonexistent_parameter": 3})

    np.testing.assert_array_equal(view.image.data, before)


# --- persistence --------------------------------------------------------------------

def test_the_recorded_mask_survives_a_project_round_trip(tmp_path, view):
    h5py = pytest.importorskip("h5py")  # noqa: F841
    from retina.io.project import load_project, save_project

    app = view.window  # the window already belongs to an Application
    _with_mask(view)
    get("Invert")().execute_on(view)

    application = Application()
    application.windows.append(app)
    path = str(tmp_path / "project.retina")
    save_project(application, path)

    fresh = Application()
    load_project(fresh, path)
    entry = fresh.windows[0].main_view.history_entries()[1]
    assert entry.mask_id == "Mask"


def test_a_project_without_a_recorded_mask_is_reread_and_replayed(tmp_path, view):
    """Backward compatibility: the fields have defaults, so an older project is intact."""
    h5py = pytest.importorskip("h5py")  # noqa: F841
    from retina.io.project import load_project, save_project

    _chain(view)
    application = Application()
    application.windows.append(view.window)
    path = str(tmp_path / "old.retina")
    save_project(application, path)

    fresh = Application()
    load_project(fresh, path)
    reread = fresh.windows[0].main_view
    assert all(e.mask_id is None for e in reread.history_entries())
    assert reread.replay(1, {"sigma": 3.0})
