"""Conventions of the gesture-driven processes — what their interface depends on.

These processes are not new: `DynamicCrop`, `CloneStamp`, `DynamicAlignment` and `DynamicPSF`
have had a scriptable core from the start. What is new is that an interface drives them with
the pointer, and therefore depends on conventions that nothing pinned down — first and
foremost the **direction of rotation**. A gesture whose result goes the opposite way from the
mouse is the worst possible feedback, and it is the kind of mistake that is hard to deduce:
`scipy.ndimage.rotate` does not document its direction in image coordinates.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from retina.model.window import ImageWindow
from retina.processes.retouch import CloneStamp, DynamicCrop


def _top_left_marker(size: int = 40) -> np.ndarray:
    """Dark image with a bright square at the top left — an asymmetric landmark."""
    data = np.zeros((size, size, 1), dtype=np.float32)
    data[2:10, 2:10, 0] = 1.0
    return data


def _corner(data: np.ndarray) -> str:
    plane = data[:, :, 0]
    ys, xs = np.nonzero(plane > 0.5)
    assert len(ys) > 0, "the marker has vanished"
    h, w = plane.shape
    return ("top" if ys.mean() < h / 2 else "bottom") + "-" + (
        "left" if xs.mean() < w / 2 else "right"
    )


def test_a_positive_angle_rotates_counterclockwise():
    """The convention the panel's rotation handle depends on.

    A marker at the top left goes to the bottom left for +90°: top-left → bottom-left is a
    **counterclockwise** rotation. The panel must therefore send a *negative* angle when the
    user drags the handle clockwise (`web/src/viewport/cropTool.ts`). If scipy were to change
    convention, this is where it would show.
    """
    data = _top_left_marker()
    assert _corner(data) == "top-left"
    assert _corner(DynamicCrop(angle=90.0)._apply(data.copy())) == "bottom-left"
    assert _corner(DynamicCrop(angle=-90.0)._apply(data.copy())) == "top-right"


def test_the_default_mode_stays_rotation_after_crop():
    """Compatibility: already saved recipes, projects and icons have no `mode`.

    The parameter is an enum rather than a boolean so that a serialisation reads on its own:
    `"mode": "rotated_rect"` says what it does, `"rotate_rect": true` says nothing.
    """
    assert DynamicCrop().mode == "after_crop"
    assert {p.id for p in DynamicCrop.parameters} == {"x0", "y0", "x1", "y1", "angle", "mode"}


def test_rotated_rect_turns_the_same_way_as_after_crop():
    """The sign convention is **shared by both modes** — that is the whole point.

    The new mode no longer calls `scipy.ndimage.rotate` but builds its own grid: nothing
    guaranteed *a priori* that the angle turns the same way there, and a user switching modes
    would see the image go the other way without understanding why. The top-left marker must
    therefore end up at the bottom left for +90° in both modes.

    Corollary on the panel side: tilting the *frame* clockwise produces content rotated
    counterclockwise — that is physically unavoidable (the frame turns on the photo), and it
    is why `cropTool.ts` negates the gesture angle in one mode and not in the other.
    """
    data = _top_left_marker()
    rotated = DynamicCrop(angle=90.0, mode="rotated_rect")._apply(data.copy())
    assert rotated.shape == data.shape, "the full-frame rectangle keeps the image size"
    assert _corner(rotated) == "bottom-left"
    assert _corner(
        DynamicCrop(angle=-90.0, mode="rotated_rect")._apply(data.copy())
    ) == "top-right"


def test_rotated_rect_outputs_exactly_the_rectangle_size():
    """What the old mode cannot do: `reshape=True` enlarges the canvas."""
    data = np.zeros((100, 200, 1), dtype=np.float32)
    corners = {"x0": 0.25, "y0": 0.25, "x1": 0.75, "y1": 0.75, "angle": 30.0}
    assert DynamicCrop(**corners, mode="rotated_rect")._apply(data).shape[:2] == (50, 100)
    enlarged = DynamicCrop(**corners)._apply(data).shape[:2]
    assert enlarged[0] > 50 and enlarged[1] > 100


def test_at_a_null_angle_both_modes_give_the_same_result():
    """Otherwise the new parameter would change the result of recipes that do not rotate.

    The equality is **exact**: at a null angle the grid falls on integer indices, where a
    bilinear interpolation returns the pixel itself.
    """
    rng = np.random.default_rng(3)
    data = rng.random((37, 53, 3)).astype(np.float32)
    corners = {"x0": 0.2, "y0": 0.1, "x1": 0.8, "y1": 0.9, "angle": 0.0}
    previous = DynamicCrop(**corners)._apply(data)
    new_item = DynamicCrop(**corners, mode="rotated_rect")._apply(data)
    assert new_item.shape == previous.shape
    assert np.array_equal(new_item, previous)


def test_rotated_rect_leaves_no_black_corner_in_the_image():
    """The whole point of the mode: a tilted inner rectangle has no empty edge.

    The old mode, for its part, fills the corners of the enlarged canvas with black — checked
    here so that the difference stays a tested claim and not a documentation promise.
    """
    data = np.full((200, 200, 1), 0.5, dtype=np.float32)
    corners = {"x0": 0.4, "y0": 0.4, "x1": 0.6, "y1": 0.6, "angle": 37.0}
    tilted = DynamicCrop(**corners, mode="rotated_rect")._apply(data)
    assert tilted.shape[:2] == (40, 40)
    assert float(tilted.min()) == pytest.approx(0.5, abs=1e-6)

    previous = DynamicCrop(**corners)._apply(data)
    assert previous.shape[0] > 40 and float(previous.min()) == 0.0


def test_rotated_rect_samples_outside_the_image_as_black():
    """A tilted rectangle that overflows is not an error: what is missing is worth zero."""
    data = np.full((60, 60, 1), 0.5, dtype=np.float32)
    out = DynamicCrop(x0=0.0, y0=0.0, x1=1.0, y1=1.0, angle=45.0, mode="rotated_rect")._apply(data)
    assert out.shape[:2] == (60, 60)
    assert float(out[0, 0, 0]) == 0.0, "the corner of the rotated square falls outside the image"
    assert float(out[30, 30, 0]) == pytest.approx(0.5, abs=1e-6)


def test_a_fractional_crop_cuts_the_right_area():
    """The parameters are fractions of the target view, not pixels."""
    data = np.zeros((100, 200, 1), dtype=np.float32)
    data[25:75, 50:150, 0] = 1.0  # exactly the central quarter
    out = DynamicCrop(x0=0.25, y0=0.25, x1=0.75, y1=0.75)._apply(data)
    assert out.shape[:2] == (50, 100)
    assert np.allclose(out, 1.0), "the crop must land right on the bright area"


@pytest.mark.parametrize("mode", ["after_crop", "rotated_rect"])
def test_a_crop_on_a_preview_is_relative_to_the_preview(mode):
    """The panel computes its fractions on the *target* view — so a preview works on its own.

    Both modes must answer the same way: the tilted rectangle is likewise built in the pixel
    frame **of the processed view**, not of the window.
    """
    win = ImageWindow(Image(np.zeros((100, 200, 1), dtype=np.float32)))
    pv = win.create_preview(50, 25, 150, 75)
    DynamicCrop(x0=0.0, y0=0.0, x1=0.5, y1=1.0, mode=mode).execute_on(pv)
    assert pv.image.width == 50 and pv.image.height == 50


def test_clone_stamp_stacks_in_a_container():
    """Several *unrelated* stamps = several instances played in order.

    A continuous stroke fits in a single instance (`points`), but independent dabs — different
    sources, different radii — remain distinct instances, played by the panel through
    `process.run_container`: one job, one echo, a guaranteed order.

    The container, on the other hand, pushes one history entry **per step** — checked here,
    because the interface announces it to the user and because an optimistic comment had first
    promised the opposite.
    """
    from retina.process.container import ProcessContainer

    data = np.zeros((40, 40, 1), dtype=np.float32)
    data[4:12, 4:12, 0] = 1.0  # bright source
    win = ImageWindow(Image(data))

    container = ProcessContainer()
    container.add(CloneStamp(src_x=8, src_y=8, dst_x=30, dst_y=8, radius=5, softness=0.0))
    container.add(CloneStamp(src_x=8, src_y=8, dst_x=30, dst_y=30, radius=5, softness=0.0))
    container.execute_on(win.main_view)

    out = win.main_view.image.data[:, :, 0]
    assert out[8, 30] > 0.5, "the first stamp must have laid down signal"
    assert out[30, 30] > 0.5, "and so must the second — the ordering must not lose one"
    assert win.main_view.history_labels() == ["initial", "CloneStamp", "CloneStamp"]


def test_clone_stamp_without_points_stays_a_single_dab():
    """The single dab has not moved — and the old "no trajectory" assertion is lifted.

    This test used to assert `not any(p.type in ("table", "pointlist"))`: the core was to
    carry **one** disc only, the interface stacking the instances. Painting by dragging makes
    that rule untenable — a two-second gesture produces dozens of discs, hence as many history
    entries and container rounds for what the user experiences as *one stroke*. `points`
    (floatlist, like `DynamicAlignment.source`) therefore carries the trajectory, and what
    remains true — and locked down here — is **compatibility**: without `points`, the process
    behaves exactly as before, and an existing script does not move by one LSB (bit-for-bit
    equivalence is held by `test_the_vectorised_clone_stamp_reproduces_the_reference`).
    """
    ids = {p.id for p in CloneStamp.parameters}
    assert ids == {"src_x", "src_y", "dst_x", "dst_y", "radius", "softness", "points"}
    assert CloneStamp().points == [], "the default must be the historical single dab"
    points = next(p for p in CloneStamp.parameters if p.id == "points")
    assert points.type == "floatlist"

    # a `points` with a single pair = the single dab, with the source described in absolute
    data = np.zeros((40, 40, 1), dtype=np.float32)
    data[4:12, 4:12, 0] = 1.0
    single = CloneStamp(src_x=8, src_y=8, dst_x=30, dst_y=30, radius=5, softness=0.2)._apply(data)
    via_stroke = CloneStamp(src_x=8, src_y=8, radius=5, softness=0.2,
                            points=[30.0, 30.0])._apply(data)
    assert np.array_equal(single, via_stroke)


def _clone_reference(data: np.ndarray, src_x: int, src_y: int, dst_x: int, dst_y: int,
                     radius: int, softness: float) -> np.ndarray:
    """The **historical** implementation of `CloneStamp._apply`, copied verbatim.

    It serves as the golden reference for the vectorised port: the double Python loop was
    readable and manifestly correct, but took 11 ms for a single disc of radius 40 — and a
    stroke asks for a hundred. Keeping the original here is what allows us to claim the
    rewrite changed nothing to the *rendering*, on randomly drawn cases.
    """
    h, w = data.shape[:2]
    r = int(radius)
    out = data.copy()
    dxs = np.arange(-r, r + 1)
    yy, xx = np.meshgrid(dxs, dxs, indexing="ij")
    dist = np.sqrt(xx * xx + yy * yy)
    soft = max(float(softness), 1e-6) * r
    alpha = np.clip((r - dist) / soft, 0.0, 1.0)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            a = alpha[dy + r, dx + r]
            if a <= 0.0:
                continue
            sy, sx = src_y + dy, src_x + dx
            ty, tx = dst_y + dy, dst_x + dx
            if 0 <= sy < h and 0 <= sx < w and 0 <= ty < h and 0 <= tx < w:
                out[ty, tx] = (1.0 - a) * data[ty, tx] + a * data[sy, sx]
    return out.astype(np.float32)


@pytest.mark.parametrize("kw", [
    {"src_x": 20, "src_y": 15, "dst_x": 40, "dst_y": 35, "radius": 7, "softness": 0.3},
    {"src_x": 20, "src_y": 15, "dst_x": 40, "dst_y": 35, "radius": 7, "softness": 0.0},  # hard
    {"src_x": 20, "src_y": 15, "dst_x": 40, "dst_y": 35, "radius": 7, "softness": 1.0},  # feathered
    {"src_x": 5, "src_y": 5, "dst_x": 3, "dst_y": 3, "radius": 9, "softness": 0.4},  # overflows
    {"src_x": 45, "src_y": 45, "dst_x": 48, "dst_y": 46, "radius": 11, "softness": 0.25},
    {"src_x": 20, "src_y": 20, "dst_x": 23, "dst_y": 20, "radius": 8, "softness": 0.5},  # overlaps
])
def test_the_vectorised_clone_stamp_reproduces_the_reference(kw):
    """Bit for bit, edges included: vectorising was not to change the rendering at all."""
    rng = np.random.default_rng(1234)
    for shape in ((60, 70, 1), (50, 50, 3)):
        data = rng.random(shape).astype(np.float32)
        assert np.array_equal(CloneStamp(**kw)._apply(data), _clone_reference(data, **kw))


def test_a_clone_stamp_stroke_equals_the_stack_of_its_dabs():
    """The central invariant of the stroke: N points ≡ N single-dab instances stacked.

    The stroke passes **over its own source area** (short offset, back and forth): that is the
    case which separates a correct implementation from one that would read the source in the
    original image. Each dab must read what the previous ones wrote — otherwise a stroke and
    its stacked equivalent would diverge from the second point on, and the gesture would no
    longer be replayable in a script.
    """
    rng = np.random.default_rng(7)
    data = rng.random((80, 80, 3)).astype(np.float32)
    pts: list[float] = []
    for i in range(40):
        pts += [30.0 + i * 0.8, 40.0 + 6.0 * np.sin(i / 3.0)]
    src = (36, 40)  # 6 px from the start: the stroke will pass back over its source

    stroke = CloneStamp(src_x=src[0], src_y=src[1], radius=9, softness=0.35,
                        points=pts)._apply(data)

    off_x, off_y = src[0] - int(round(pts[0])), src[1] - int(round(pts[1]))
    stacked = data
    for i in range(0, len(pts), 2):
        px, py = int(round(pts[i])), int(round(pts[i + 1]))
        stacked = CloneStamp(src_x=px + off_x, src_y=py + off_y, dst_x=px, dst_y=py,
                             radius=9, softness=0.35)._apply(stacked)

    assert np.array_equal(stroke, stacked)
    assert not np.array_equal(stroke, data), "a stroke that paints nothing would prove nothing"


def test_a_clone_stamp_stroke_makes_a_single_history_entry():
    """One gesture = one stroke = **one** undoable step, where N instances gave N."""
    data = np.zeros((40, 40, 1), dtype=np.float32)
    data[4:12, :, 0] = 1.0  # bright band: the source *travels* with the stroke, it must
    win = ImageWindow(Image(data))  # stay bright all along the run
    CloneStamp(src_x=8, src_y=8, radius=4, softness=0.2,
               points=[24.0, 24.0, 27.0, 24.0, 30.0, 24.0]).execute_on(win.main_view)
    assert win.main_view.history_labels() == ["initial", "CloneStamp"]
    out = win.main_view.image.data[:, :, 0]
    assert out[24, 24] > 0.5 and out[24, 30] > 0.5, "both ends must be painted"


def test_clone_stamp_points_outside_the_frame_are_clipped():
    """A stroke that leaves the frame is cut off; it neither raises nor wraps around.

    The mouse leaves the image without warning; refusing the whole gesture for that would be
    absurd, and an unclipped `numpy` would write on the other side through negative indexing.
    """
    data = np.zeros((30, 30, 1), dtype=np.float32)
    data[10:20, 10:20, 0] = 1.0
    out = CloneStamp(src_x=15, src_y=15, radius=6, softness=0.3,
                     points=[2.0, 2.0, -50.0, -50.0, 28.0, 28.0, 500.0, 500.0])._apply(data)
    assert out.shape == data.shape
    assert np.isfinite(out).all()
    assert out[2, 2] > 0.0, "the point on the edge must paint its visible crescent"


def test_an_odd_number_of_clone_stamp_points_is_refused():
    """An odd flat list is a call error, not a last point to be guessed."""
    with pytest.raises(ValueError, match="even number"):
        CloneStamp(points=[1.0, 2.0, 3.0])._apply(np.zeros((10, 10, 1), dtype=np.float32))


def test_dynamic_alignment_requires_pairs():
    """A single pair is refused by the domain — the panel must say so, not hide it."""
    from retina.processes.registration import DynamicAlignment

    data = np.zeros((20, 20, 1), dtype=np.float32)
    with pytest.raises(ValueError):
        DynamicAlignment(source=[1.0, 1.0], target=[2.0, 2.0])._apply(data)


def _star_field(size: int = 80) -> np.ndarray:
    """Synthetic field: three gaussians of known widths on a noisy background."""
    rng = np.random.default_rng(7)
    field = (rng.random((size, size)) * 0.002).astype(np.float32)
    ys, xs = np.mgrid[0:size, 0:size]
    for (cx, cy, sigma) in [(20, 20, 1.6), (55, 30, 1.6), (35, 60, 1.6)]:
        field += (0.8 * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma**2)))).astype(
            np.float32
        )
    return np.clip(field, 0, 1)[:, :, None]


def test_dynamic_psf_exposes_the_per_star_detail():
    """Without `stars`, the interface could neither draw the ellipses nor list the measures.

    `result` carried only three medians. Both semi-axes (`fwhm_x`/`fwhm_y`) are needed for the
    drawing: reconstructing them from the FWHM and the eccentricity would be possible, but
    they are computed just before being thrown away.
    """
    pytest.importorskip("photutils")
    from retina.processes.psf import DynamicPSF

    psf = DynamicPSF(fwhm=3.0, threshold_sigma=5.0)
    result = psf.measure(Image(_star_field()))

    assert result["n_stars"] >= 2
    assert len(result["stars"]) == result["n_stars"]
    star = result["stars"][0]
    for key in ("x", "y", "fwhm", "fwhm_x", "fwhm_y", "eccentricity", "flux", "theta"):
        assert key in star, f"{key} is missing from a star's detail"
    # The medians stay, so as not to break what was already reading them.
    assert result["fwhm"] == pytest.approx(
        float(np.median([e["fwhm"] for e in result["stars"]]))
    )


def test_dynamic_psf_positions_replaces_detection():
    """The "click a star" gesture is a parameter, hence scriptable — not a GUI-only power."""
    pytest.importorskip("photutils")
    from retina.processes.psf import DynamicPSF

    field = Image(_star_field())
    forced = DynamicPSF(positions=[20.0, 20.0]).measure(field)
    assert forced["n_stars"] == 1
    assert forced["stars"][0]["x"] == pytest.approx(20.0, abs=1.5)
    assert forced["stars"][0]["y"] == pytest.approx(20.0, abs=1.5)

    # Two forced positions bypass `max_stars`, which bounds the automatic detection.
    two = DynamicPSF(positions=[20.0, 20.0, 55.0, 30.0], max_stars=1).measure(field)
    assert two["n_stars"] == 2


def test_a_dynamic_psf_position_on_a_flat_area_returns_nothing():
    """A fit on background **converges** to its initial value without saying so.

    That is why the core requires the peak of the model to exceed the local dispersion. The
    panel must therefore be able to tell "no star here" from "measurement at zero".
    """
    pytest.importorskip("photutils")
    from retina.processes.psf import DynamicPSF

    flat = Image(np.full((60, 60, 1), 0.1, dtype=np.float32))
    assert DynamicPSF(positions=[30.0, 30.0]).measure(flat)["stars"] == []
