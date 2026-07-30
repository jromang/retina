"""Astrometry: WCS plumbing + annotation (with a synthetic WCS)."""

from __future__ import annotations

import numpy as np
import pytest
from retina import Application, Image, View, get


def _synthetic_wcs(h, w):
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [w / 2, h / 2]
    wcs.wcs.cdelt = [-0.001, 0.001]  # 3.6 arcsec/px
    wcs.wcs.crval = [10.0, 20.0]  # RA/Dec of the centre
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def test_window_wcs_roundtrip():
    app = Application()
    win = app.new_window(Image(np.zeros((64, 64, 1), dtype=np.float32)))
    assert not win.has_astrometric_solution
    win.wcs = _synthetic_wcs(64, 64)
    assert win.has_astrometric_solution

    sky = win.image_to_celestial(32.0, 32.0)
    x, y = win.celestial_to_image(sky)
    assert x == pytest.approx(32.0, abs=1e-3)
    assert y == pytest.approx(32.0, abs=1e-3)


def test_annotation_draws_grid():
    """Burn-in mode — "flatten into the image", now explicit."""
    app = Application()
    win = app.new_window(Image(np.full((64, 64, 1), 0.2, dtype=np.float32)))
    win.wcs = _synthetic_wcs(64, 64)
    get("Annotation")(
        grid_spacing=0.02, line_width=0.03, render_mode="pixels"
    ).execute_on(win.main_view)

    out = win.main_view.image.data
    assert out.shape[2] == 3  # switched to RGB
    green = (out[:, :, 1] > 0.9) & (out[:, :, 0] < 0.5)
    assert green.sum() > 0  # grid lines have been drawn


def test_annotation_by_default_leaves_the_pixels_alone():
    """The default is the overlay: annotating a measured image must not modify it.

    Burning a grid into the pixels destroys the data — the values under the strokes are lost
    to any later measurement. That is acceptable as an *export* ("flatten"), not as an
    inspection gesture, and inspection is what one does most often.
    """
    app = Application()
    origin = np.full((64, 64, 1), 0.2, dtype=np.float32)
    win = app.new_window(Image(origin.copy()))
    win.wcs = _synthetic_wcs(64, 64)

    assert get("Annotation")(grid_spacing=0.02).execute_on(win.main_view) is True

    assert np.array_equal(win.main_view.image.data, origin), "pixels must be untouched"
    # Nothing to undo: no history entry for a display-only annotation.
    assert win.main_view.history_labels() == ["initial"]

    overlays = win.viewport.overlays
    assert overlays, "the grid must be laid down as an overlay"
    assert {o["kind"] for o in overlays} <= {"lines", "text"}
    assert all(o["tag"] == "annotation" for o in overlays)
    lines = next(o for o in overlays if o["kind"] == "lines")
    # Polylines in image coordinates, not a pixel mask.
    assert len(lines["segments"]) >= 2
    assert all(len(segment) >= 2 for segment in lines["segments"])


def test_a_replayed_annotation_replaces_its_grid():
    """A second pass must not stack a second grid on top of the first."""
    app = Application()
    win = app.new_window(Image(np.full((64, 64, 1), 0.2, dtype=np.float32)))
    win.wcs = _synthetic_wcs(64, 64)
    proc = get("Annotation")(grid_spacing=0.02)
    proc.execute_on(win.main_view)
    first = len(win.viewport.overlays)
    proc.execute_on(win.main_view)
    assert len(win.viewport.overlays) == first


def test_the_annotation_overlay_does_not_erase_the_other_tools():
    """Tags partition: a tool open alongside keeps its markers."""
    app = Application()
    win = app.new_window(Image(np.full((64, 64, 1), 0.2, dtype=np.float32)))
    win.wcs = _synthetic_wcs(64, 64)
    app.add_overlay("markers", tag="dbe", points=[(10, 10)])
    get("Annotation")(grid_spacing=0.02).execute_on(win.main_view)
    assert any(o.get("tag") == "dbe" for o in win.viewport.overlays)


def test_the_catalog_annotation_overlay_places_its_markers():
    app = Application()
    win = app.new_window(Image(np.full((64, 64, 1), 0.2, dtype=np.float32)))
    win.wcs = _synthetic_wcs(64, 64)
    pixels = [(16, 16), (48, 48)]
    objs = []
    for px, py in pixels:
        sky = win.wcs.pixel_to_world(px, py)
        objs.append((sky.ra.deg, sky.dec.deg, 9.0))

    proc = get("CatalogAnnotation")(marker_radius=4.0).set_objects(objs)
    proc.execute_on(win.main_view)

    assert proc.count == len(pixels)
    assert np.allclose(win.main_view.image.data, 0.2), "pixels must stay untouched"
    ellipses = next(o for o in win.viewport.overlays if o["kind"] == "ellipses")
    positions = [(round(item["x"]), round(item["y"])) for item in ellipses["items"]]
    assert positions == pixels
    # The radius is in image pixels: the marker therefore follows the zoom, where a burnt-in
    # circle kept its screen size whatever the magnification.
    assert all(item["rx"] == 4.0 for item in ellipses["items"])


def test_annotation_requires_wcs():
    view = View(Image(np.zeros((8, 8, 1), dtype=np.float32)), view_id="v")
    with pytest.raises(ValueError):
        get("Annotation")().execute_on(view)  # no window/WCS


def test_platesolve_online_requires_api_key():
    app = Application()
    # 12 synthetic stars, to get past detection before the key check
    field = np.zeros((64, 64), dtype=np.float32)
    rng = np.random.default_rng(0)
    for _ in range(20):
        cy, cx = rng.uniform(6, 58), rng.uniform(6, 58)
        ys, xs = np.mgrid[0:64, 0:64]
        field += (
            0.9 * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 1.5**2)))
        ).astype(np.float32)
    win = app.new_window(Image(np.clip(field, 0, 1)[:, :, None]))
    with pytest.raises(ValueError):
        get("PlateSolve")(backend="astrometry_net", api_key="").execute_on(win.main_view)


def test_platesolve_default_backend_is_auto():
    # default = ``auto``: ASTAP under Windows, the Python ``astrometry`` solver elsewhere.
    proc = get("PlateSolve")()
    assert proc.backend == "auto"
    import sys

    expected = "astap" if sys.platform == "win32" else "astrometry"
    assert proc._resolve_backend() == expected


def test_platesolve_astap_plumbing():
    """End-to-end ASTAP plumbing: exe found, database detected, output parsed.

    A synthetic field matches no real patch of sky → ASTAP must answer cleanly "not solved"
    (PLTSOLVD=F), which validates the whole chain (subprocess, FITS write, .ini read).
    Skipped if the ASTAP bundle is missing.
    """
    if get("PlateSolve")()._find_astap() is None:
        pytest.skip("astap_cli not bundled (vendor/astap) — platform-specific test")

    app = Application()
    rng = np.random.default_rng(0)
    field = np.zeros((256, 256), dtype=np.float32)
    ys, xs = np.mgrid[0:256, 0:256]
    for _ in range(40):
        cy, cx = rng.uniform(10, 246), rng.uniform(10, 246)
        field += (
            0.9 * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 1.6**2)))
        ).astype(np.float32)
    win = app.new_window(Image(np.clip(field, 0, 1)[:, :, None]))

    # BOUNDED search (0.5° radius around an arbitrary position) → ASTAP gives up quickly on a
    # synthetic field, instead of a blind scan of the whole sky (> 2 min).
    # The guard checks that the chain runs cleanly — either a WCS is set, or an explicit ASTAP
    # RuntimeError is raised, NEVER another error (missing exe, broken parse).
    try:
        get("PlateSolve")(backend="astap", ra=10.0, dec=10.0, radius=0.5,
                          timeout=60).execute_on(win.main_view)
        assert win.main_view.window.wcs is not None
    except RuntimeError as exc:
        assert "astap" in str(exc).lower()


def test_catalog_annotation_offline():
    """Annotating an explicitly supplied catalogue (offline) through the WCS."""
    app = Application()
    win = app.new_window(Image(np.full((64, 64, 1), 0.2, dtype=np.float32)))
    win.wcs = _synthetic_wcs(64, 64)

    # objects placed at known pixels → we recover their (ra, dec) through the WCS
    pixels = [(16, 16), (48, 48), (32, 10)]
    objs = []
    for (px, py) in pixels:
        sky = win.wcs.pixel_to_world(px, py)
        objs.append((sky.ra.deg, sky.dec.deg, 9.0))

    # `render_mode="pixels"` spelled out: the default is now the overlay, which leaves the
    # pixels alone. This test is about burn-in, that is, about "flatten into the image".
    proc = get("CatalogAnnotation")(
        marker_radius=4.0, labels=False, render_mode="pixels"
    ).set_objects(objs)
    proc.execute_on(win.main_view)

    out = win.main_view.image.data
    assert out.shape[2] == 3  # RGB
    assert proc.count == len(pixels)  # all projected inside the frame
    # a yellow marker is present near the first targeted pixel
    y, x = 16, 16
    patch = out[max(0, y - 6):y + 6, max(0, x - 6):x + 6]
    yellow = (patch[:, :, 0] > 0.8) & (patch[:, :, 1] > 0.8) & (patch[:, :, 2] < 0.5)
    assert yellow.any()


def test_catalog_annotation_requires_wcs():
    view = View(Image(np.zeros((8, 8, 1), dtype=np.float32)), view_id="v")
    with pytest.raises(ValueError):
        get("CatalogAnnotation")().set_objects([]).execute_on(view)
