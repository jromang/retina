"""Viewport parity: zoom/pan/channel/modes/readout all doable WITHOUT the shell.

Guards the console-completeness pillar for the viewport: every display capability
(zoom, fit, coordinate transforms, channel selection, interaction modes, readout) is
exercisable headless through ``app.*`` / ``ImageWindow``, and echoes its Python.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import (
    Application,
    Image,
    InteractionMode,
    MaskDisplayMode,
    TransparencyMode,
)
from retina.model.stf import STF, ChannelSTF


def test_stf_apply_accepts_raw_ndarray():
    """STF.apply must accept a bare ndarray (the magnifier path) — an ndarray also has
    a ``.data`` attribute (a memoryview), hence the regression that was fixed."""
    stf = STF(channels=[ChannelSTF(0.0, 0.25, 1.0)] * 3)
    arr = np.full((4, 4, 3), 0.1, dtype=np.float32)
    out = stf.apply(arr)
    assert out.shape == (4, 4, 3)
    assert np.allclose(out, 0.25, atol=1e-3)  # mtf(0.25, 0.1) = 0.25


def _win(app, w=200, h=100, c=3):
    img = Image((np.random.default_rng(0).random((h, w, c)) * 0.4).astype(np.float32))
    win = app.new_window(img)
    app.set_active_window(win)
    win.viewport.set_geometry(w, h, 1.0)  # explicit geometry in headless mode
    return win


def test_coord_roundtrip():
    app = Application()
    win = _win(app)
    app.set_zoom(2.0)
    for pt in [(0.0, 0.0), (50.0, 25.0), (199.0, 99.0), (37.3, 12.8)]:
        vp = win.image_to_viewport(pt)
        back = win.viewport_to_image(vp)
        assert np.allclose(back, pt, atol=1e-6)


def test_zoom_to_fit_math():
    app = Application()
    win = _win(app, w=200, h=100)  # viewport 200x100
    # without magnification: min(200/200, 100/100)=1.0, capped at 1.0
    app.zoom_to_fit()
    assert abs(win.zoom - 1.0) < 1e-9
    # larger viewport + magnification allowed → zoom > 1
    win.viewport.set_geometry(800, 400, 1.0)
    app.zoom_to_fit(allow_magnification=True)
    assert abs(win.zoom - 4.0) < 1e-9
    # center re-framed on the middle of the image
    assert win.center == (100.0, 50.0)


def test_zoom_in_out_and_1_1():
    app = Application()
    win = _win(app)
    app.set_zoom(1.0)
    app.zoom_in()
    assert win.zoom == 2.0
    app.zoom_out()
    app.zoom_out()
    assert win.zoom == 0.5
    app.zoom_1_1()
    assert win.zoom == 1.0


def test_channel_and_modes():
    app = Application()
    win = _win(app)
    app.set_display_channel("red")
    assert win.viewport.display_channel == "red"
    app.set_interaction_mode(InteractionMode.PAN)
    assert win.viewport.interaction_mode is InteractionMode.PAN
    app.set_mask_display_mode(MaskDisplayMode.OVERLAY_GREEN)
    assert win.viewport.mask_display_mode is MaskDisplayMode.OVERLAY_GREEN
    app.set_stf_enabled(False)
    assert win.viewport.stf_enabled is False
    assert win.current_view.stf_enabled is False


def test_readout_probe():
    app = Application()
    win = _win(app)
    r = win.readout(50, 25, n=1)
    assert r is not None and r["x"] == 50 and r["y"] == 25
    assert len(r["channels"]) == 3
    # outside the image → None
    assert win.readout(9999, 9999) is None
    # 3x3 probe: mean/min/max are consistent
    r3 = win.readout(50, 25, n=3)
    ch0 = r3["channels"][0]
    assert ch0["min"] <= ch0["mean"] <= ch0["max"]


def _synthetic_wcs(width: int, height: int):
    """Plain tangential WCS: 1″/px, field center at (10°, 41°) — the M31 field."""
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [width / 2, height / 2]
    wcs.wcs.crval = [10.0, 41.0]
    wcs.wcs.cdelt = [-1 / 3600, 1 / 3600]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def test_readout_without_astrometry_promises_nothing():
    app = Application()
    win = _win(app)
    read = win.readout(50, 25)
    assert read is not None and read["celestial"] is None


def test_readout_returns_celestial_coordinates():
    pytest.importorskip("astropy")
    app = Application()
    win = _win(app, w=200, h=100)
    win.wcs = _synthetic_wcs(200, 100)

    center = win.readout(100, 50)
    assert center is not None and center["celestial"] is not None
    assert center["celestial"]["ra"] == pytest.approx(10.0, abs=1e-3)
    assert center["celestial"]["dec"] == pytest.approx(41.0, abs=1e-3)

    # One pixel to the right: RA *decreases* (negative cdelt, the sky-from-Earth convention).
    right = win.readout(101, 50)
    assert right is not None and right["celestial"]["ra"] < center["celestial"]["ra"]


def test_readout_on_a_preview_reapplies_the_rectangle_origin():
    """The trap: the WCS belongs to the window, the probe works in the view's frame.

    Without re-applying the preview's origin, the coordinates displayed would point at a
    different place in the sky — and would stay perfectly plausible, hence impossible to
    catch by eye.
    """
    pytest.importorskip("astropy")
    app = Application()
    win = _win(app, w=200, h=100)
    win.wcs = _synthetic_wcs(200, 100)
    expected = win.readout(120, 60)["celestial"]

    pv = app.new_preview(100, 50, 160, 90, "Zone")
    app.select_view(pv.id)
    # (20, 10) in the preview = (120, 60) in the window.
    actual = win.readout(20, 10)["celestial"]
    assert actual["ra"] == pytest.approx(expected["ra"], abs=1e-9)
    assert actual["dec"] == pytest.approx(expected["dec"], abs=1e-9)


def test_pivot_zoom_keeps_point_fixed():
    """Magnifier-tool zoom: the clicked point stays under the cursor (viewport unchanged)."""
    app = Application()
    win = _win(app, w=200, h=100)
    app.set_zoom(1.0)
    pivot = (150.0, 30.0)
    before = win.image_to_viewport(pivot)
    app.zoom_in(pivot=pivot)
    after = win.image_to_viewport(pivot)
    assert win.zoom == 2.0
    assert np.allclose(before, after, atol=1e-6)
    app.zoom_out(pivot=pivot)
    assert win.zoom == 1.0
    assert np.allclose(win.image_to_viewport(pivot), before, atol=1e-6)


def test_new_preview_via_app():
    app = Application()
    echoed: list[str] = []
    app.on_echo = echoed.append
    win = _win(app)
    pv = app.new_preview(10, 20, 60, 70)
    assert pv in win.previews
    assert pv.image.width == 50 and pv.image.height == 50
    assert any("app.new_preview(10, 20, 60, 70" in e for e in echoed)


def test_display_channels_full_set():
    app = Application()
    win = _win(app)
    for ch in ("rgb", "red", "green", "blue", "L", "cie_L", "cie_a", "cie_b",
               "hue", "saturation", "value", "intensity"):
        app.set_display_channel(ch)
        assert win.viewport.display_channel == ch


def test_overlays_and_transparency_api():
    app = Application()
    echoed: list[str] = []
    app.on_echo = echoed.append
    win = _win(app)
    ov = app.add_overlay("markers", points=[(1, 2), (3, 4)], color=(1, 1, 0, 1), size=8)
    app.add_overlay("text", text="NGC", pos=(5, 5))
    assert len(win.viewport.overlays) == 2 and ov in win.viewport.overlays
    app.clear_overlays()
    assert win.viewport.overlays == []
    app.set_transparency_mode(TransparencyMode.HIDE)
    assert win.viewport.transparency_mode is TransparencyMode.HIDE
    joined = "\n".join(echoed)
    assert "app.add_overlay('markers'" in joined
    assert "app.clear_overlays()" in joined
    assert "retina.TransparencyMode.HIDE" in joined


def test_overlay_kinds_and_tags():
    """The five shapes, and clearing by tag.

    The tag is not a convenience: two tools open at once (PSF ellipses and a crop rectangle)
    would clear each other without it, and the second gesture would make the first vanish
    with nothing to explain why.
    """
    app = Application()
    win = _win(app)
    app.add_overlay("markers", points=[(1, 2)], tag="psf")
    app.add_overlay("ellipses", items=[{"x": 1, "y": 2, "rx": 3, "ry": 2, "theta": 0.4}], tag="psf")
    app.add_overlay("rects", rects=[(0, 0, 10, 10)], angle=15.0, tag="crop")
    app.add_overlay("lines", segments=[[(0, 0), (5, 5)]])
    assert len(win.viewport.overlays) == 4

    app.clear_overlays(tag="psf")
    remaining = win.viewport.overlays
    assert [o["kind"] for o in remaining] == ["rects", "lines"]
    # An untagged overlay is not swept away when another tag is cleared.
    app.clear_overlays(tag="crop")
    assert [o["kind"] for o in win.viewport.overlays] == ["lines"]
    app.clear_overlays()
    assert win.viewport.overlays == []


def test_unknown_overlay_kind_raises():
    app = Application()
    _win(app)
    with pytest.raises(ValueError):
        app.add_overlay("hologram", points=[(1, 2)])


def test_overlay_tag_is_echoed_so_it_can_be_replayed():
    app = Application()
    echoed: list[str] = []
    app.on_echo = echoed.append
    _win(app)
    app.add_overlay("markers", tag="dbe", points=[(1, 2)])
    app.clear_overlays(tag="dbe")
    joined = "\n".join(echoed)
    assert "app.add_overlay('markers', tag='dbe', points=[(1, 2)])" in joined
    assert "app.clear_overlays(tag='dbe')" in joined


def test_on_change_hook_fires():
    app = Application()
    win = _win(app)
    fired = []
    win.viewport.on_change = lambda: fired.append(True)
    app.set_zoom(3.0)
    app.set_display_channel("blue")
    assert len(fired) == 2


def test_echo_and_headless():
    app = Application()
    echoed: list[str] = []
    app.on_echo = echoed.append
    _win(app)
    app.set_zoom(2.0)
    app.zoom_to_fit()
    app.set_display_channel("green")
    app.set_interaction_mode(InteractionMode.ZOOM_IN)
    app.set_stf_enabled(True)
    joined = "\n".join(echoed)
    assert "app.set_zoom(2.0)" in joined
    assert "app.set_display_channel('green')" in joined
    assert "retina.InteractionMode.ZOOM_IN" in joined
    # The absence of the shell can no longer be asserted here: `tests/server/` loads aiohttp
    # into the same process. The real guarantee lives in tests/server/test_headless_parity.py,
    # which starts a fresh interpreter.
