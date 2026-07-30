"""ProcessContainer: execution, XML serialisation, and recipe from history."""

from __future__ import annotations

import contextlib

import numpy as np
from retina import (
    GaussianConvolution,
    HistogramTransformation,
    Image,
    PixelMath,
    ProcessContainer,
    View,
)


def _img():
    return Image((np.random.default_rng(7).random((24, 32, 1)) * 0.3).astype(np.float32))


def test_container_matches_manual_chain():
    img = _img()
    pc = ProcessContainer([GaussianConvolution(sigma=1.5), PixelMath(expression="img * 1.2")])
    out = pc.execute_on_image(img)

    manual = GaussianConvolution(sigma=1.5).execute_on_image(img)
    manual = PixelMath(expression="img * 1.2").execute_on_image(manual)
    np.testing.assert_allclose(out.data, manual.data, atol=1e-6)


def test_container_on_view_pushes_one_step_per_process():
    view = View(_img(), view_id="v")
    ProcessContainer(
        [GaussianConvolution(sigma=1.0), HistogramTransformation(midtones=0.4)]
    ).execute_on(view)
    assert view.history_index == 2
    assert len(view.history_processes()) == 2


def test_container_xml_roundtrip():
    pc = ProcessContainer(
        [GaussianConvolution(sigma=2.5), HistogramTransformation(shadows=0.1, midtones=0.3)]
    )
    xml = pc.to_xml()
    restored = ProcessContainer.from_xml(xml)
    assert [p.process_id for p in restored] == [p.process_id for p in pc]
    assert restored.processes[0].values() == pc.processes[0].values()
    assert restored.processes[1].values() == pc.processes[1].values()
    # replayable identically
    img = _img()
    np.testing.assert_allclose(
        pc.execute_on_image(img).data, restored.execute_on_image(img).data, atol=1e-6
    )


def test_recipe_from_history_reproduces_result():
    """Reproducibility: replay a view's history onto a fresh image."""
    img = _img()
    view = View(img.copy(), view_id="src")
    GaussianConvolution(sigma=1.5).execute_on(view)
    PixelMath(expression="img * 1.1").execute_on(view)

    recipe = view.recipe()
    assert len(recipe) == 2

    reproduced = recipe.execute_on_image(img.copy())
    np.testing.assert_allclose(reproduced.data, view.image.data, atol=1e-6)


def test_container_save_load(tmp_path):
    pc = ProcessContainer([PixelMath(expression="sqrt(img)")])
    p = tmp_path / "recipe.xml"
    pc.save(str(p))
    loaded = ProcessContainer.load(str(p))
    assert loaded.processes[0].values() == pc.processes[0].values()


# --- disabled step --------------------------------------------------------------
def test_a_disabled_step_is_skipped():
    """The familiar gesture: try a recipe without one of its steps, without losing it."""
    img = _img()
    pc = ProcessContainer([GaussianConvolution(sigma=1.5), PixelMath(expression="img * 1.2")])
    pc.disable(0)

    expected = PixelMath(expression="img * 1.2").execute_on_image(img)
    np.testing.assert_allclose(pc.execute_on_image(img).data, expected.data, atol=1e-6)
    assert pc.enabled(0) is False and pc.enabled(1) is True
    assert len(pc) == 2  # disabled, not removed


def test_a_disabled_step_pushes_no_history():
    view = View(_img(), view_id="v")
    pc = ProcessContainer([GaussianConvolution(sigma=1.0), PixelMath(expression="img * 1.1")])
    pc.disable(0)
    pc.execute_on(view)
    assert view.history_index == 1


def test_the_flags_follow_additions():
    pc = ProcessContainer([PixelMath(expression="img")])
    pc.disable(0)
    pc.add(GaussianConvolution(sigma=1.0))
    # The added step is enabled, and the previous one has not changed state.
    assert (pc.enabled(0), pc.enabled(1)) == (False, True)


def test_an_out_of_range_index_raises():
    pc = ProcessContainer([PixelMath(expression="img")])
    for call in (lambda: pc.disable(3), lambda: pc.enabled(-1), lambda: pc.set_mask(9, "m")):
        try:
            call()
        except IndexError:
            continue
        raise AssertionError("an out-of-range index must raise")


# --- per-step mask --------------------------------------------------------------
def _window_with(image):
    from retina.model.window import ImageWindow

    return ImageWindow(image, window_id="W")


def test_a_step_mask_limits_its_effect():
    """The mask is set on the window for the duration of the step — that is where
    `Process.execute_on` reads it."""
    start = Image(np.full((8, 8, 1), 0.5, dtype=np.float32))
    window = _window_with(start.copy())
    # Mask: left half protected (0), right half exposed (1).
    half = np.zeros((8, 8, 1), dtype=np.float32)
    half[:, 4:, :] = 1.0

    pc = ProcessContainer([PixelMath(expression="img * 0.0")])
    pc.set_mask(0, "mask")
    pc.execute_on(window.main_view, resolve_mask=lambda _id: Image(half))

    result = window.main_view.image.data
    np.testing.assert_allclose(result[:, :4, :], 0.5, atol=1e-6)  # protected
    np.testing.assert_allclose(result[:, 4:, :], 0.0, atol=1e-6)  # processed


def test_the_step_mask_is_removed_afterwards():
    """The point that breaks: without the `finally`, the mask would contaminate everything
    that follows."""
    window = _window_with(Image(np.full((8, 8, 1), 0.5, dtype=np.float32)))
    assert window.mask is None

    pc = ProcessContainer([PixelMath(expression="img * 0.5")])
    pc.set_mask(0, "mask")
    pc.execute_on(window.main_view, resolve_mask=lambda _id: Image(np.ones((8, 8, 1), np.float32)))

    assert window.mask is None
    assert window.mask_inverted is False


def test_the_step_mask_is_removed_even_if_the_step_raises():
    window = _window_with(Image(np.full((8, 8, 1), 0.5, dtype=np.float32)))
    pc = ProcessContainer([PixelMath(expression="this_function_does_not_exist(img)")])
    pc.set_mask(0, "mask")
    with contextlib.suppress(Exception):
        pc.execute_on(
            window.main_view, resolve_mask=lambda _id: Image(np.ones((8, 8, 1), np.float32))
        )
    assert window.mask is None


def test_the_window_mask_is_returned_intact():
    """A masked step must not steal the mask the user had set."""
    window = _window_with(Image(np.full((8, 8, 1), 0.5, dtype=np.float32)))
    own = Image(np.full((8, 8, 1), 0.25, dtype=np.float32))
    window.set_mask(own, inverted=True)

    pc = ProcessContainer([PixelMath(expression="img * 0.5")])
    pc.set_mask(0, "other")
    pc.execute_on(window.main_view, resolve_mask=lambda _id: Image(np.ones((8, 8, 1), np.float32)))

    assert window.mask is own
    assert window.mask_inverted is True


def test_the_flags_survive_the_xml_round_trip():
    pc = ProcessContainer(
        [GaussianConvolution(sigma=2.0), PixelMath(expression="img"), PixelMath(expression="img")]
    )
    pc.disable(1)
    pc.set_mask(2, "Preview01", invert=True)

    restored = ProcessContainer.from_xml(pc.to_xml())
    assert restored.enabled(0) is True and restored.enabled(1) is False
    assert restored.mask_id(2) == "Preview01" and restored.mask_inverted(2) is True
    assert restored.mask_id(0) is None


def test_an_ordinary_recipe_keeps_its_original_xml():
    """Attributes are only written when they depart from the default: files already saved
    are read back without conversion, and the ones we write stay readable."""
    xml = ProcessContainer([PixelMath(expression="img")]).to_xml()
    assert "enabled" not in xml and "mask" not in xml


def test_the_flags_survive_the_json_round_trip():
    pc = ProcessContainer([PixelMath(expression="img"), PixelMath(expression="img * 2")])
    pc.disable(0)
    pc.set_mask(1, "Mask01")

    restored = ProcessContainer.from_dicts(pc.to_dicts())
    assert restored.enabled(0) is False
    assert restored.mask_id(1) == "Mask01" and restored.mask_inverted(1) is False


def test_the_python_source_replays_the_flags():
    pc = ProcessContainer([PixelMath(expression="img"), PixelMath(expression="img * 2")])
    pc.disable(0)
    pc.set_mask(1, "Mask01", invert=True)
    source = pc.to_python_source("view")
    assert "pc.disable(0)" in source
    assert "pc.set_mask(1, 'Mask01', True)" in source
