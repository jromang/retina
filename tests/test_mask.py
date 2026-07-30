"""Masks: a process only modifies the white region of the mask."""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, GaussianConvolution, Image, PixelMath
from retina.model.window import ImageWindow


def _half_mask(h=10, w=10):
    """Mask: left half white (1), right half black (0)."""
    m = np.zeros((h, w, 1), dtype=np.float32)
    m[:, : w // 2, :] = 1.0
    return Image(m)


def test_mask_protects_black_region():
    win = ImageWindow(Image(np.full((10, 10, 1), 0.8, dtype=np.float32)))
    win.set_mask(_half_mask())
    PixelMath(expression="img*0").execute_on(win.main_view)  # everything to 0…
    out = win.main_view.image.data
    assert np.allclose(out[:, :5, 0], 0.0)   # white region → processed
    assert np.allclose(out[:, 5:, 0], 0.8)   # black region → protected


def test_mask_inverted_swaps():
    win = ImageWindow(Image(np.full((10, 10, 1), 0.8, dtype=np.float32)))
    win.set_mask(_half_mask(), inverted=True)
    PixelMath(expression="img*0").execute_on(win.main_view)
    out = win.main_view.image.data
    assert np.allclose(out[:, :5, 0], 0.8)   # inverted white → protected
    assert np.allclose(out[:, 5:, 0], 0.0)   # inverted black → processed


def test_mask_disabled_has_no_effect():
    win = ImageWindow(Image(np.full((10, 10, 1), 0.8, dtype=np.float32)))
    win.set_mask(_half_mask())
    win.mask_enabled = False
    PixelMath(expression="img*0").execute_on(win.main_view)
    assert np.allclose(win.main_view.image.data, 0.0)  # mask ignored → everything processed


def test_mask_partial_blend():
    """A mask at 0.5 blends halfway: 0.8 -> 0.5*0 + 0.5*0.8 = 0.4."""
    win = ImageWindow(Image(np.full((6, 6, 1), 0.8, dtype=np.float32)))
    win.set_mask(Image(np.full((6, 6, 1), 0.5, dtype=np.float32)))
    PixelMath(expression="img*0").execute_on(win.main_view)
    assert np.allclose(win.main_view.image.data, 0.4)


def test_mask_visible_does_not_change_processing():
    """Hiding the mask is a *display* gesture: processes keep being subject to it.

    That is the Show Mask / Enable Mask distinction. Conflating the two would mean a user
    who hides the rendering to judge their image then processes it unprotected.
    """
    app = Application()
    win = app.new_window(Image(np.full((10, 10, 1), 0.8, dtype=np.float32)), window_id="light")
    win.set_mask(_half_mask())
    app.set_mask_visible(False)
    assert win.viewport.mask_visible is False
    assert win.mask_enabled is True

    app.apply(PixelMath(expression="img*0"))
    out = win.main_view.image.data
    assert np.allclose(out[:, :5, 0], 0.0)   # white region → processed despite invisibility
    assert np.allclose(out[:, 5:, 0], 0.8)   # black region → still protected


def test_mask_visible_is_echoed():
    app = Application()
    echoed: list[str] = []
    app.on_echo = echoed.append
    app.new_window(Image(np.zeros((4, 4, 1), dtype=np.float32)), window_id="light")
    app.set_mask_visible(False)
    assert "app.set_mask_visible(False)" in echoed


def test_mask_dimension_mismatch_raises():
    win = ImageWindow(Image(np.full((10, 10, 1), 0.8, dtype=np.float32)))
    win.set_mask(Image(np.zeros((5, 5, 1), dtype=np.float32)))
    with pytest.raises(ValueError):
        GaussianConvolution(sigma=1.0).execute_on(win.main_view)


def test_window_mask_on_a_smaller_preview():
    """The mask belongs to the window; a preview receives the matching sub-region.

    That is the expected behaviour: you set a mask once, then try it out on a preview.
    Previously, the first process on the preview raised on a dimension comparison — so the
    "try it on a preview" loop was unusable as soon as a mask was active.
    """
    win = ImageWindow(Image(np.full((10, 10, 1), 0.8, dtype=np.float32)))
    win.set_mask(_half_mask())  # left half processed, right half protected
    # Preview straddling the mask boundary: columns 3..7 of the window.
    preview = win.create_preview(3, 0, 7, 10, "trial")

    PixelMath(expression="img*0").execute_on(preview)

    out = preview.image.data
    assert out.shape[:2] == (10, 4)
    assert np.allclose(out[:, :2, 0], 0.0)  # columns 3-4: under the white → processed
    assert np.allclose(out[:, 2:, 0], 0.8)  # columns 5-6: under the black → protected


def test_mask_via_app_by_window_id():
    app = Application()
    target = app.new_window(Image(np.full((10, 10, 1), 0.8, dtype=np.float32)), window_id="light")
    app.new_window(_half_mask(), window_id="mymask")
    app.set_active_window(target)
    app.set_mask("mymask")
    app.apply(PixelMath(expression="img*0"))
    out = target.main_view.image.data
    assert np.allclose(out[:, :5, 0], 0.0) and np.allclose(out[:, 5:, 0], 0.8)


def test_star_mask_generates_new_window():
    """StarMask produces a mask in a NEW window, without destroying the source."""
    from retina import get

    rng = np.random.default_rng(0)
    field = (rng.random((64, 64)) * 0.01).astype(np.float32)
    ys, xs = np.mgrid[0:64, 0:64]
    for (cx, cy) in [(20, 20), (40, 45), (30, 55)]:
        field += (
            0.9 * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 1.5**2)))
        ).astype(np.float32)
    field = np.clip(field, 0, 1)[:, :, None]

    app = Application()
    src = app.new_window(Image(field), window_id="light")
    before = len(app.windows)
    app.apply(get("StarMask")(fwhm=3.0, threshold_sigma=5.0, radius=4.0))

    assert len(app.windows) == before + 1                       # new window created
    assert np.allclose(src.main_view.image.data, field)          # source untouched
    mask_win = app.windows[-1]
    assert mask_win.main_view.image.channels == 1                # single-channel mask
    assert mask_win.id == "light_StarMask"


def test_shape_changing_process_ignores_mask():
    """ChannelExtraction (3→1) changes the geometry: the mask does not apply (no error)."""
    from retina import get

    win = ImageWindow(Image(np.full((8, 8, 3), 0.5, dtype=np.float32)))
    win.set_mask(Image(np.ones((8, 8, 1), dtype=np.float32)))
    get("ChannelExtraction")(channel="R").execute_on(win.main_view)
    assert win.main_view.image.channels == 1  # ran without a mask error
