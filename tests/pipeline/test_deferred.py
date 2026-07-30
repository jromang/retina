"""The points that had been deferred, now that they are handled.

Dark scale optimization, SubframeSelector eccentricity and expressions, real drizzle. Each
was filed as "deferred"; these tests pin down what they now do.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.io.fits import load_fits, save_fits
from retina.model.image import Image
from retina.pipeline import plan, scan
from retina.pipeline.presets import Preset
from retina.process.registry import get
from retina.processes.calibration import optimize_dark_scale
from retina.processes.subframe import DEFAULT_WEIGHTING

# --- dark scale optimization -----------------------------------------------------------

def pattern_and_sky(seed=0, size=64):
    """A fixed pixel-to-pixel pattern (the dark) and a smooth background (the sky)."""
    rng = np.random.default_rng(seed)
    pattern = rng.normal(0.0, 0.02, (size, size, 1)).astype(np.float32)
    ys, xs = np.mgrid[0:size, 0:size]
    sky = (0.3 + 0.0005 * (ys + xs))[:, :, None].astype(np.float32)
    return pattern, sky


@pytest.mark.parametrize("true_scale", [0.5, 1.0, 1.7])
def test_the_optimization_recovers_the_injected_factor(true_scale):
    pattern, sky = pattern_and_sky()
    rng = np.random.default_rng(1)
    light = sky + true_scale * pattern + rng.normal(0, 0.001, pattern.shape).astype(np.float32)

    found = optimize_dark_scale(light, pattern, initial=1.0, amplitude=3.0)

    assert found == pytest.approx(true_scale, rel=0.05)


def test_the_optimization_beats_the_exposure_ratio_when_it_lies():
    """Dark current is not perfectly linear in time; the ratio lies a little."""
    pattern, sky = pattern_and_sky(seed=2)
    light = sky + 1.3 * pattern

    def graininess(k):
        residual = (light - k * pattern)[:, :, 0]
        deviations = np.concatenate([np.diff(residual, axis=0).ravel(),
                                 np.diff(residual, axis=1).ravel()])
        return float(np.median(np.abs(deviations - np.median(deviations))))

    optimized = optimize_dark_scale(light, pattern, initial=1.0, amplitude=3.0)

    assert graininess(optimized) < graininess(1.0)


def test_the_optimization_rejects_mismatched_geometries():
    with pytest.raises(ValueError, match="geometry"):
        optimize_dark_scale(np.zeros((8, 8, 1), np.float32), np.zeros((4, 4, 1), np.float32))


def test_the_process_uses_the_optimized_scale(tmp_path):
    pattern, sky = pattern_and_sky(seed=3)
    path = str(tmp_path / "darkc.fits")
    save_fits(path, Image(np.abs(pattern)))
    light = Image(np.clip(sky + 1.4 * np.abs(pattern), 0, 1))

    process = get("ImageCalibration")(master_dark=path, dark_scale=1.0,
                                      dark_optimize=True, dark_optimize_range=3.0,
                                      pedestal_mode="none")
    process.execute_on_image(light)

    assert process.optimized_scale == pytest.approx(1.4, rel=0.1)


def test_without_optimization_the_declared_scale_is_respected(tmp_path):
    path = str(tmp_path / "d.fits")
    save_fits(path, Image(np.full((8, 8, 1), 0.2, dtype=np.float32)))

    out = get("ImageCalibration")(master_dark=path, dark_scale=0.5,
                                  pedestal_mode="none").execute_on_image(
        Image(np.full((8, 8, 1), 0.5, dtype=np.float32)))

    assert np.allclose(out.data, 0.4, atol=1e-5)


def test_the_plan_only_optimizes_when_the_dark_is_scaled(raws_mono, tmp_path):
    """On a dark of the right exposure there is nothing to look for — and looking is costly."""
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path))
    calibration = p.step("calibrate_light_L_5s_bin1_g120_m10C").processes[0]

    assert calibration.dark_optimize is False


# --- eccentricity and expressions -------------------------------------------------------

def field(elongation=1.0, n=18, size=96, seed=0):
    """A field of Gaussian stars, optionally elongated along x."""
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    image = np.zeros((size, size), dtype=np.float64)
    for y0, x0 in rng.uniform(12, size - 12, size=(n, 2)):
        image += 0.6 * np.exp(-(((ys - y0) ** 2) / (2 * 1.4**2)
                                + ((xs - x0) ** 2) / (2 * (1.4 * elongation) ** 2)))
    image += rng.normal(0.05, 0.004, (size, size))
    return np.clip(image, 0, 1)[:, :, None].astype(np.float32)


def field_frames(tmp_path, elongations) -> list[str]:
    paths = []
    for i, a in enumerate(elongations):
        p = str(tmp_path / f"c{i}.fits")
        save_fits(p, Image(field(a, seed=i)))
        paths.append(p)
    return paths


def test_eccentricity_tells_elongated_stars_apart(tmp_path):
    """An exposure whose tracking drifted will draw streaks in the integration."""
    paths = field_frames(tmp_path, [1.0, 2.5])
    measures = get("SubframeSelector")(frames=paths).measure()

    circular, elongated = measures[0]["eccentricity"], measures[1]["eccentricity"]
    assert circular < 0.4
    assert elongated > circular + 0.2


def test_the_normalized_measures_put_the_best_at_one(tmp_path):
    measures = get("SubframeSelector")(frames=field_frames(tmp_path, [1.0, 2.0, 3.0])).measure()

    # eccentricity: smaller = better, so the roundest one is worth 1
    assert measures[0]["eccentricity_n"] == pytest.approx(1.0)
    assert min(m["eccentricity_n"] for m in measures) == pytest.approx(0.0)


def test_a_homogeneous_batch_does_not_manufacture_a_hierarchy(tmp_path):
    """Without this guard, insignificant gaps would be amplified to the point of absurdity."""
    path = str(tmp_path / "u.fits")
    save_fits(path, Image(field(1.0)))
    measures = get("SubframeSelector")(frames=[path] * 3).measure()

    assert {round(m["weight"], 6) for m in measures} == {round(1 / 3, 6)}


def test_the_approval_expression_rejects_and_explains(tmp_path):
    paths = field_frames(tmp_path, [1.0, 3.0])
    measures = get("SubframeSelector")(frames=paths,
                                      approval="eccentricity < 0.5").measure()

    assert measures[0]["approved"] is True
    assert measures[1]["approved"] is False
    assert measures[1]["weight"] == 0.0
    # the rejected frame stays in the report: one has to be able to see why
    assert len(measures) == 2


def test_the_weights_of_approved_frames_sum_to_one(tmp_path):
    paths = field_frames(tmp_path, [1.0, 1.2, 3.0])
    measures = get("SubframeSelector")(frames=paths,
                                      approval="eccentricity < 0.5").measure()

    assert sum(m["weight"] for m in measures) == pytest.approx(1.0)


def test_a_custom_weighting_expression_is_respected(tmp_path):
    paths = field_frames(tmp_path, [1.0, 2.5])
    equals = get("SubframeSelector")(frames=paths, weighting="1.0").measure()

    assert [m["weight"] for m in equals] == pytest.approx([0.5, 0.5])


def test_the_default_weighting_favors_round_stars(tmp_path):
    paths = field_frames(tmp_path, [1.0, 3.0])
    measures = get("SubframeSelector")(frames=paths).measure()

    assert "eccentricity_n" in DEFAULT_WEIGHTING
    assert measures[0]["weight"] > measures[1]["weight"]


def test_an_invalid_expression_raises_clearly(tmp_path):
    paths = field_frames(tmp_path, [1.0])

    with pytest.raises(ValueError, match="invalid expression"):
        get("SubframeSelector")(frames=paths, weighting="fwhm +").measure()


def test_the_expressions_travel_through_the_preset(raws_mono, tmp_path):
    settings = Preset(name="strict", approval="stars > 0", weighting_expression="snr_n")
    p = plan(scan(raws_mono), settings, output_dir=str(tmp_path))
    measure = p.step("measure_light_L_5s_bin1_g120_m10C").process

    assert measure.approval == "stars > 0"
    assert measure.weighting == "snr_n"


# --- drizzle ------------------------------------------------------------------------------

def dithered_frames(tmp_path, offsets, size=64, seed=0, sigma=0.8, count=20):
    """Fine stars, moved by a fraction of a pixel from one exposure to the next."""
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
    positions = rng.uniform(10, size - 10, size=(count, 2))
    paths, transformations = [], []
    for i, (dy, dx) in enumerate(offsets):
        image = np.zeros((size, size), dtype=np.float64)
        for y0, x0 in positions:
            image += 0.5 * np.exp(-(((ys - y0 + dy) ** 2 + (xs - x0 + dx) ** 2)
                                    / (2 * sigma**2)))
        p = str(tmp_path / f"d{i}.fits")
        save_fits(p, Image(np.clip(image, 0, 1)[:, :, None].astype(np.float32)))
        paths.append(p)
        transformations += [1.0, 0.0, dx, 0.0, 1.0, dy]
    return paths, transformations


DITHER = [(0.0, 0.0), (0.5, 0.0), (0.0, 0.5), (0.5, 0.5), (0.25, 0.25), (0.75, 0.25)]


def test_drizzle_restores_sub_pixel_detail(tmp_path):
    """That is the whole point: a shrunken drop over dithered exposures recovers sharpness."""
    paths, transformations = dithered_frames(tmp_path, DITHER)

    rebuilt = get("DrizzleIntegration")(frames=paths, scale=2, pixfrac=0.6,
                                            transforms=transformations).combine()
    flattened = get("DrizzleIntegration")(frames=paths, scale=2, pixfrac=1.0).combine()

    assert rebuilt.shape == (128, 128, 1)
    assert rebuilt.max() > flattened.max() * 1.1


def test_the_shrunken_drop_concentrates_the_signal(tmp_path):
    paths, transformations = dithered_frames(tmp_path, DITHER)

    narrow = get("DrizzleIntegration")(frames=paths, scale=2, pixfrac=0.4,
                                    transforms=transformations).combine()
    wide = get("DrizzleIntegration")(frames=paths, scale=2, pixfrac=1.0,
                                      transforms=transformations).combine()

    assert narrow.max() > wide.max()


def test_the_transforms_must_match_the_frames(tmp_path):
    paths, _ = dithered_frames(tmp_path, DITHER[:2])

    with pytest.raises(ValueError, match="6 per frame"):
        get("DrizzleIntegration")(frames=paths, transforms=[1, 0, 0]).combine()


def test_without_coverage_the_output_is_zero_and_invents_nothing(tmp_path):
    paths, transformations = dithered_frames(tmp_path, [(0.0, 0.0)])
    out = get("DrizzleIntegration")(frames=paths, scale=3, pixfrac=0.2,
                                    transforms=transformations, supersample=2).combine()

    # a very narrow drop over a single exposure is bound to leave holes
    assert (out == 0.0).any()
    assert np.isfinite(out).all()


def test_drizzle_estimates_its_transforms_from_a_reference(tmp_path):
    # wider and more numerous stars: astroalign needs triangles to match
    paths, _ = dithered_frames(tmp_path, [(0.0, 0.0), (2.0, -1.0), (-1.0, 2.0)],
                                size=96, sigma=1.6, count=30)

    out = get("DrizzleIntegration")(frames=paths, scale=2, pixfrac=0.7,
                                    reference_path=paths[0]).combine()

    assert out.shape == (192, 192, 1)
    assert out.max() > 0.3  # the exposures did stack on top of each other


def test_the_drizzle_preset_bypasses_registration(raws_mono, tmp_path):
    """Registering first would destroy the very information drizzle feeds on."""
    p = plan(scan(raws_mono), Preset(name="dz", drizzle=True), output_dir=str(tmp_path))

    assert not [s for s in p.steps if s.id.startswith("register_")]
    step = p.step("integrate_light_L_5s_bin1_g120_m10C")
    assert step.process.process_id == "DrizzleIntegration"
    assert step.bindings == {"reference_path": "@reference"}


def test_drizzle_without_measurements_is_flagged(raws_mono, tmp_path):
    p = plan(scan(raws_mono), Preset(name="dz", drizzle=True, measure=False),
             output_dir=str(tmp_path))

    assert any("drizzle without measurements" in n for n in p.notes)


def test_a_trailed_exposure_is_detected_not_ignored(tmp_path):
    """The trap: with no measurement, a botched exposure reads as a perfect frame."""
    path = str(tmp_path / "trailed.fits")
    save_fits(path, Image(field(elongation=3.0)))

    measure = get("SubframeSelector")(frames=[path]).measure()[0]

    assert measure["stars"] > 5           # the trailed stars are indeed seen…
    assert measure["eccentricity"] > 0.5  # …and penalized


def test_drizzle_covers_the_edges(tmp_path):
    """The drop of pixel 0 spills half a pixel out: excluding it would amputate the rim."""
    path = str(tmp_path / "flat.fits")
    save_fits(path, Image(np.full((8, 8, 1), 0.4, dtype=np.float32)))

    out = get("DrizzleIntegration")(frames=[path], scale=2, pixfrac=1.0).combine()

    assert out.shape == (16, 16, 1)
    assert np.allclose(out, 0.4, atol=1e-3)


# --- resilience: one lost frame does not take the batch down with it --------------------

def test_a_corrupt_frame_does_not_take_the_batch_down(raws_mono, tmp_path):
    """Over two hundred exposures, a truncated file happens. Losing the 199 others is absurd."""
    import shutil

    from retina.pipeline.runner import run

    source = tmp_path / "raws"
    shutil.copytree(raws_mono, source)
    corrupt = sorted(source.glob("light_L_*.fits"))[1]
    corrupt.write_bytes(b"not FITS at all")

    p = plan(scan(str(source)), "auto", output_dir=str(tmp_path / "out"))
    report = run(p)

    assert len(report.results) == 2
    assert any("excluded" in n for n in report.notes)
    # the lost frame no longer shows up in the integration, and the weights are realigned
    integration = p.step("integrate_light_L_5s_bin1_g120_m10C")
    assert len(integration.inputs) == 3
    assert len(integration.process.weights) == 3


def test_an_entirely_lost_group_raises(tmp_path):
    """Discarding frame after frame until nothing is left would be worse than raising."""
    from retina.pipeline.runner import run
    from retina.pipeline.synthetic import make_dataset

    source = tmp_path / "raws"
    source.mkdir()
    make_dataset(str(source), "mono", filters=("L",))
    for path in source.glob("bias_*.fits"):
        path.write_bytes(b"not FITS at all")

    p = plan(scan(str(source)), "auto", output_dir=str(tmp_path / "out"))
    with pytest.raises(ValueError, match="no readable frames"):
        run(p)


def test_cancellation_is_not_treated_as_a_lost_frame(raws_mono, tmp_path):
    from retina.pipeline.runner import run
    from retina.process import context
    from retina.process.progress import ProcessCancelled, ProgressMonitor

    monitor = ProgressMonitor()
    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path))
    context.set_monitor(monitor)
    try:
        with pytest.raises(ProcessCancelled):
            run(p, on_progress=lambda f, m: monitor.cancel() if f and f > 0.2 else None)
    finally:
        context.set_monitor(None)


# --- automatic cropping ------------------------------------------------------------------

def test_autocrop_removes_the_partially_covered_edges(tmp_path):
    """In the integration a half-seen edge is not zero: measure on the registered frames."""
    registered = []
    for i in range(4):
        frame = np.full((40, 40, 1), 0.3, dtype=np.float32)
        frame[: 2 + i, :, :] = 0.0  # each exposure sees a different top edge
        path = str(tmp_path / f"r{i}.fits")
        save_fits(path, Image(frame))
        registered.append(path)

    integrated = np.mean([load_fits(f)[0].data for f in registered], axis=0)
    # in the integration, row 3 is seen by 2 exposures out of 4: attenuated, not zero
    assert 0.0 < float(integrated[3].max()) < 0.3

    ac = get("AutoCrop")(frames=registered)
    y0, y1, x0, x1 = ac.bounds(integrated)

    assert y0 == 5  # the most offset exposure hides five rows
    assert (y1, x0, x1) == (40, 0, 40)


def test_without_frames_autocrop_only_sees_the_fully_empty_edges():
    image = np.full((20, 20, 1), 0.3, dtype=np.float32)
    image[:3, :, :] = 0.0

    assert get("AutoCrop")().bounds(image) == (3, 20, 0, 20)


def test_autocrop_leaves_a_healthy_image_alone():
    image = np.full((20, 20, 1), 0.4, dtype=np.float32)

    assert get("AutoCrop")().bounds(image) == (0, 20, 0, 20)


def test_the_cropping_is_bounded():
    """An image legitimately dark along its edges must not be devoured."""
    image = np.zeros((20, 20, 1), dtype=np.float32)
    image[9:11, 9:11, :] = 0.5

    y0, y1, _, _ = get("AutoCrop")(max_fraction=0.25).bounds(image)
    assert y0 <= 5 and y1 >= 15


def test_registration_fills_the_out_of_field_with_zero(raws_mono, tmp_path):
    """Filling with the median would manufacture sky where nothing was ever observed."""
    from retina.pipeline.runner import run

    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path / "out"))
    run(p)
    registered = p.step("register_light_L_5s_bin1_g120_m10C").outputs
    empty_items = [int((np.abs(load_fits(f)[0].data).max(axis=2) == 0).sum()) for f in registered]

    assert max(empty_items) > 0  # dithering is bound to leave some out-of-field area


def test_the_pipeline_crops_by_default(raws_mono, tmp_path):
    from retina.pipeline.runner import run

    p = plan(scan(raws_mono), "auto", output_dir=str(tmp_path))
    report = run(p)

    integrated = load_fits(p.step("integrate_light_L_5s_bin1_g120_m10C").outputs[0])[0].data
    final = load_fits(report.results[0])[0].data

    assert final.shape[0] < integrated.shape[0]
    assert final.shape[1] < integrated.shape[1]


# --- weight floor -------------------------------------------------------------------------

def test_the_weight_floor_discards_unworthy_exposures(tmp_path):
    """An exposure twenty times worse than the best degrades rejection and brings nothing."""
    paths = field_frames(tmp_path, [1.0, 1.05])
    measures = get("SubframeSelector")(frames=paths, weighting="index + 0.001",
                                      min_weight=0.5).measure()

    assert measures[0]["approved"] is False
    assert measures[0]["rejected_by"] == "min_weight"
    assert measures[1]["weight"] == pytest.approx(1.0)


def test_a_zero_floor_excludes_nobody(tmp_path):
    paths = field_frames(tmp_path, [1.0, 1.05])
    measures = get("SubframeSelector")(frames=paths, weighting="index + 0.001",
                                      min_weight=0.0).measure()

    assert all(m["approved"] for m in measures)


# --- overscan: the unexposed area, revealed by a real sensor -----------------------------

def image_with_overscan(height=32, width=40, useful=32, level=0.02, signal=0.3):
    """An image whose last columns are not exposed, with a per-row drift."""
    data = np.zeros((height, width, 1), dtype=np.float32)
    drift = np.linspace(0.0, 0.004, height, dtype=np.float32)[:, None]
    data[:, :useful, 0] = signal + level + drift        # useful area: signal + bias
    data[:, useful:, 0] = level + drift                 # overscan: bias alone
    return data


def test_the_overscan_removes_the_bias_of_that_very_exposure():
    """A master bias gives the mean of a series; the overscan, the value of this exposure."""
    data = image_with_overscan()
    out = get("Overscan")(bias_section="[33:40]",
                          trim_section="[1:32, :]").execute_on_image(Image(data)).data

    assert out.shape == (32, 32, 1)
    assert np.allclose(out, 0.3, atol=1e-5)  # the per-row drift is gone


def test_the_overscan_corrects_row_by_row():
    """The readout register's drift runs along the readout; it is not uniform."""
    data = image_with_overscan()
    levels = get("Overscan")(bias_section="[33:40]")._levels(data)

    assert levels.shape == (32, 1, 1)          # one level per row
    assert levels.max() - levels.min() == pytest.approx(0.004, abs=1e-4)


def test_the_global_mode_returns_a_scalar():
    levels = get("Overscan")(bias_section="[33:40]", axis="global")._levels(
        image_with_overscan())

    assert levels.shape == ()


def test_a_one_dimensional_section_denotes_the_columns():
    """`[33:40]` is an interval in x. Completing it on the wrong side would slice rows."""
    from retina.processes.preprocess import _fits_slices

    y, x, c = _fits_slices("[33:40]", 3)

    assert y == slice(None)
    assert x == slice(32, 40)
    assert c == slice(None)  # the channels follow whole


def test_trimming_alone_is_possible():
    out = get("Overscan")(trim_section="[1:32, :]").execute_on_image(
        Image(image_with_overscan())).data

    assert out.shape == (32, 32, 1)


def test_with_no_section_the_overscan_does_nothing():
    data = image_with_overscan()
    out = get("Overscan")().execute_on_image(Image(data)).data

    assert np.array_equal(out, data)


def test_a_section_outside_the_frame_raises():
    with pytest.raises(ValueError, match="empty region"):
        get("Overscan")(bias_section="[500:510]").execute_on_image(
            Image(image_with_overscan()))


def test_the_median_withstands_a_cosmic_ray_in_the_overscan():
    """A mean would let a cosmic ray shift the level of an entire row."""
    data = image_with_overscan()
    data[5, 35, 0] = 1.0

    by_median = get("Overscan")(bias_section="[33:40]", method="median")._levels(data)
    by_mean = get("Overscan")(bias_section="[33:40]", method="mean")._levels(data)

    assert abs(float(by_median[5, 0, 0]) - float(by_median[4, 0, 0])) < 1e-3
    assert abs(float(by_mean[5, 0, 0]) - float(by_mean[4, 0, 0])) > 0.1


# --- integration into the pipeline ---------------------------------------------------------

def dataset_with_overscan(tmp_path):
    """A tiny dataset whose headers declare BIASSEC/TRIMSEC, like a real CCD."""
    source = tmp_path / "raws"
    source.mkdir()
    sections = {"BIASSEC": "[33:40]", "TRIMSEC": "[1:32, :]"}
    for kind, n, expo in (("Bias Frame", 3, 0.0), ("Dark Frame", 3, 5.0),
                          ("Flat Field", 3, 1.0), ("Light Frame", 3, 5.0)):
        for i in range(n):
            data = image_with_overscan(signal=0.3 if "Light" in kind else 0.1)
            save_fits(str(source / f"{kind.split()[0].lower()}_{i}.fits"), Image(data),
                      {"IMAGETYP": kind, "EXPTIME": expo, "XBINNING": 1,
                       "FILTER": "L", **sections})
    return scan(str(source))


def test_the_pipeline_detects_the_overscan_in_the_header(tmp_path):
    """Making it be typed in sensor by sensor would be an admission: the convention is standard."""
    inventory = dataset_with_overscan(tmp_path)

    assert inventory.frames[0].biassec == "[33:40]"
    assert inventory.frames[0].trimsec == "[1:32, :]"


def test_the_overscan_comes_before_everything_else(tmp_path):
    """After a master bias, the pedestal would be subtracted twice."""
    p = plan(dataset_with_overscan(tmp_path), "auto", output_dir=str(tmp_path / "out"))
    names = [s.id for s in p.steps]

    assert names[0].startswith("overscan_")
    assert max(i for i, n in enumerate(names) if n.startswith("overscan_")) < \
        min(i for i, n in enumerate(names) if n.startswith("master_"))


def test_every_frame_type_is_trimmed(tmp_path):
    """A trimmed master does not apply to a light that is not."""
    p = plan(dataset_with_overscan(tmp_path), "auto", output_dir=str(tmp_path / "out"))
    types = {s.id.split("overscan_")[1].split("_")[0]
             for s in p.steps if s.id.startswith("overscan_")}

    assert types == {"bias", "dark", "flat", "light"}


def test_the_masters_are_indeed_built_on_the_corrected_frames(tmp_path):
    p = plan(dataset_with_overscan(tmp_path), "auto", output_dir=str(tmp_path / "out"))

    assert p.step("master_bias_bin1_xC").inputs == p.step("overscan_bias_bin1_xC").outputs


def test_the_pipeline_with_overscan_completes(tmp_path):
    from retina.pipeline.runner import run

    p = plan(dataset_with_overscan(tmp_path), Preset(name="short", measure=False,
                                                     register=False),
             output_dir=str(tmp_path / "out"))
    report = run(p)
    final = load_fits(report.results[0])[0].data

    assert final.shape[1] == 32  # trimmed from 40 down to 32 columns
    assert np.isfinite(final).all()


def test_the_preset_can_disable_the_overscan(tmp_path):
    p = plan(dataset_with_overscan(tmp_path), Preset(name="raw", overscan=False),
             output_dir=str(tmp_path / "out"))

    assert not [s for s in p.steps if s.id.startswith("overscan_")]


def test_a_supplied_master_is_not_corrected_twice(tmp_path):
    """Whoever built it already did it: doing it again would subtract twice."""
    source = tmp_path / "lib"
    source.mkdir()
    save_fits(str(source / "masterBias.fits"), Image(image_with_overscan()),
              {"IMAGETYP": "Master Bias", "XBINNING": 1, "BIASSEC": "[33:40]"})
    p = plan(scan(str(source)), "auto", output_dir=str(tmp_path / "out"))

    assert not [s for s in p.steps if s.id.startswith("overscan_")]
