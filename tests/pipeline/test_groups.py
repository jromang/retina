"""Frame grouping, and matching calibration masters to lights.

The matching cases are built straight as :class:`FrameInfo`: they bear on decision rules,
not on pixels, and one set of files per case would be both slow and unreadable.
"""

from __future__ import annotations

import pytest
from retina.pipeline.groups import (
    FrameGroup,
    group_frames,
    match_calibration,
    survey,
)
from retina.pipeline.scan import FrameInfo, Inventory, scan


def frame(kind: str, *, filter: str | None = None, expo: float | None = None,
          binning: int = 1, temp: float | None = -10.0, size: tuple[int, int] = (100, 100),
          name: str = "f") -> FrameInfo:
    return FrameInfo(path=f"/data/{name}_{kind}_{filter}_{expo}_{binning}.fits", kind=kind,
                     filter=filter, exposure=expo, binning=binning, temperature=temp,
                     width=size[0], height=size[1])


def key(groups: list[FrameGroup], kind: str) -> list[str]:
    return sorted(g.key for g in groups if g.kind == kind)


# --- grouping ------------------------------------------------------------------------

def test_the_synthetic_raws_form_the_expected_groups(raws_mono):
    groups = scan(raws_mono).groups()

    assert key(groups, "bias") == ["bias_bin1_g120_m10C"]
    assert key(groups, "dark") == ["dark_5s_bin1_g120_m10C"]
    assert key(groups, "flat") == ["flat_L_bin1_g120_m10C", "flat_R_bin1_g120_m10C"]
    assert key(groups, "light") == ["light_L_5s_bin1_g120_m10C", "light_R_5s_bin1_g120_m10C"]
    assert all(len(g) in (3, 4) for g in groups)


def test_the_filter_does_not_count_for_darks():
    """Shutter closed: two darks do not differ by whichever filter was mounted."""
    groups = group_frames([frame("dark", filter="L", expo=300.0),
                            frame("dark", filter="Ha", expo=300.0)])

    assert len(groups) == 1
    assert groups[0].filter is None


def test_the_exposure_does_not_count_for_flats():
    """Flats shot at automatic brightness vary in exposure without changing meaning."""
    groups = group_frames([frame("flat", filter="L", expo=1.0),
                            frame("flat", filter="L", expo=2.5)])

    assert len(groups) == 1
    assert groups[0].filter == "L"


def test_the_filter_separates_flats_and_lights():
    groups = group_frames([frame("flat", filter="L"), frame("flat", filter="Ha"),
                            frame("light", filter="L", expo=60.0),
                            frame("light", filter="Ha", expo=60.0)])

    assert len(groups) == 4


def test_geometry_and_binning_are_hard_criteria():
    """Applying a master of another size is the mistake that ruins a night."""
    groups = group_frames([frame("bias", size=(100, 100)),
                            frame("bias", size=(200, 200)),
                            frame("bias", binning=2)])

    assert len(groups) == 3


def test_exposure_tolerances_differ_by_frame_type():
    """2 s for lights, 10 s for darks — a dark's signal varies slowly."""
    lights = group_frames([frame("light", expo=300.0), frame("light", expo=303.0)])
    darks = group_frames([frame("dark", expo=300.0), frame("dark", expo=303.0)])

    assert len(lights) == 2
    assert len(darks) == 1


def test_temperature_separates_the_groups():
    groups = group_frames([frame("dark", expo=300.0, temp=-10.0),
                            frame("dark", expo=300.0, temp=+20.0)])

    assert len(groups) == 2


def test_unknown_frames_are_set_aside():
    """Classifying them by default would manufacture wrong masters."""
    groups = group_frames([frame("unknown"), frame("bias")])

    assert [g.kind for g in groups] == ["bias"]


def test_an_excluded_frame_counts_in_no_group():
    """Excluding a frame must remove it from the processing, not merely from the display."""
    rejected = frame("bias", name="bad")
    rejected.excluded = True
    groups = group_frames([rejected, frame("bias", name="good")])

    assert len(groups) == 1
    assert [f.path for f in groups[0].frames] == ["/data/good_bias_None_None_1.fits"]


def test_a_fully_excluded_group_disappears():
    """Otherwise the matching would hunt a master for it, and the plan would hold an empty step."""
    flats = [frame("flat", filter="L", name=f"f{i}") for i in range(3)]
    for f in flats:
        f.excluded = True

    groups = group_frames([*flats, frame("light", filter="L", expo=300.0)])

    assert [g.kind for g in groups] == ["light"]
    assert match_calibration(groups)[groups[0].key].flat is None


def test_an_unknown_value_is_absorbed_by_the_group():
    groups = group_frames([frame("dark", expo=None, temp=None),
                            frame("dark", expo=300.0, temp=-10.0)])

    assert len(groups) == 1
    assert groups[0].exposure == 300.0
    assert groups[0].temperature == -10.0


# --- matching ------------------------------------------------------------------------

def match_for(frames: list[FrameInfo], kind: str = "light"):
    groups = group_frames(frames)
    target = next(g for g in groups if g.kind == kind)
    return match_calibration(groups)[target.key]


def test_with_an_exact_dark_the_bias_is_not_subtracted_twice():
    """A master dark already carries the bias: subtracting it removes the pedestal."""
    m = match_for([frame("light", filter="L", expo=300.0), frame("dark", expo=300.0),
                   frame("bias", expo=0.0), frame("flat", filter="L", expo=1.0)])

    assert m.dark is not None
    assert m.bias is None
    assert m.flat is not None
    assert m.dark_scale == 1.0
    assert not m.scaled


def test_without_a_dark_the_bias_is_the_only_subtraction():
    m = match_for([frame("light", filter="L", expo=300.0), frame("bias", expo=0.0)])

    assert m.dark is None
    assert m.bias is not None


def test_with_a_dark_of_another_exposure_the_dark_current_is_scaled():
    """Scaling a dark requires extracting its current → bias + dark current."""
    m = match_for([frame("light", filter="L", expo=150.0), frame("dark", expo=300.0),
                   frame("bias", expo=0.0)])

    assert m.scaled
    assert m.dark_scale == pytest.approx(0.5)
    assert m.bias is not None  # indispensable to debias the dark before scaling it
    assert any("scaled" in n for n in m.notes)


def test_without_a_bias_scaling_is_refused_and_explained():
    """Better an approximate calibration that says so than a silently wrong one."""
    m = match_for([frame("light", filter="L", expo=150.0), frame("dark", expo=300.0)])

    assert not m.scaled
    assert m.dark is not None
    assert any("no master bias" in n for n in m.notes)


def test_a_dark_too_far_off_is_set_aside():
    m = match_for([frame("light", filter="L", expo=10.0), frame("dark", expo=300.0),
                   frame("bias", expo=0.0)])

    assert m.dark is None
    assert m.bias is not None
    assert any("too far from" in n for n in m.notes)


def test_the_dark_closest_in_exposure_is_chosen():
    m = match_for([frame("light", filter="L", expo=300.0),
                   frame("dark", expo=120.0, name="a"), frame("dark", expo=300.0, name="b"),
                   frame("bias", expo=0.0)])

    assert m.dark.exposure == 300.0


def test_the_flat_is_chosen_by_filter():
    m = match_for([frame("light", filter="Ha", expo=300.0),
                   frame("flat", filter="L", expo=1.0), frame("flat", filter="Ha", expo=1.0)])

    assert m.flat.filter == "Ha"


def test_a_missing_flat_for_the_filter_is_reported():
    m = match_for([frame("light", filter="Ha", expo=300.0), frame("flat", filter="L")])

    assert m.flat is None
    assert any("no flat for filter" in n for n in m.notes)


def test_a_master_of_another_binning_is_never_retained():
    m = match_for([frame("light", filter="L", expo=300.0),
                   frame("dark", expo=300.0, binning=2),
                   frame("flat", filter="L", binning=2)])

    assert m.dark is None
    assert m.flat is None


def test_a_flat_is_calibrated_by_its_flat_dark_alone():
    """A dark of the same exposure carries bias + current: it is enough on its own."""
    groups = group_frames([frame("flat", filter="L", expo=2.0),
                            frame("dark", expo=2.0, name="fd"),
                            frame("bias", expo=0.0)])
    m = match_calibration(groups)[next(g for g in groups if g.kind == "flat").key]

    assert m.dark is not None
    assert m.bias is None
    assert any("flat-dark" in n for n in m.notes)


def test_a_flat_without_a_flat_dark_is_calibrated_by_the_bias():
    """A 300 s dark is not a flat-dark: a flat's exposure accumulates no dark current."""
    m = match_for([frame("flat", filter="L", expo=1.0), frame("dark", expo=300.0),
                   frame("bias", expo=0.0)], kind="flat")

    assert m.dark is None
    assert m.bias is not None


def test_the_matching_of_the_synthetic_set_is_complete(raws_mono):
    groups = scan(raws_mono).groups()
    matches = match_calibration(groups)

    lights = [m for k, m in matches.items() if k.startswith("light")]
    assert len(lights) == 2
    for m in lights:
        assert m.dark is not None       # 5 s dark = the lights' exposure
        assert m.bias is None           # the exact dark already carries the bias
        assert m.flat is not None
        assert m.flat.filter == m.target.filter
        assert not m.scaled

    flats = [m for k, m in matches.items() if k.startswith("flat")]
    assert len(flats) == 2
    for m in flats:
        assert m.bias is not None       # no 1 s flat-dark in the set
        assert m.dark is None


def test_the_match_is_serializable(raws_mono):
    groups = scan(raws_mono).groups()
    m = next(v for k, v in match_calibration(groups).items() if k.startswith("light"))
    data = m.to_dict()

    assert data["target"].startswith("light")
    assert data["dark"].startswith("dark")
    assert data["dark_scale"] == 1.0
    assert isinstance(data["notes"], list)


def test_the_group_is_serializable(raws_mono):
    group = scan(raws_mono).groups()[0]
    rebuilt = FrameGroup.from_dict(group.to_dict())

    assert rebuilt.key == group.key
    assert rebuilt.paths == group.paths
    assert rebuilt.geometry == group.geometry


# --- sensor and rig identity ----------------------------------------------------------

def frame_gain(gain: float | None, kind: str = "light", **kw) -> FrameInfo:
    return FrameInfo(path=f"/{kind}_{gain}_{kw.get('tel', 'T')}.fits", kind=kind,
                     gain=gain, exposure=300.0, filter=kw.get("filter"), binning=1,
                     temperature=-10.0, width=100, height=100,
                     extra={"TELESCOP": kw["tel"]} if "tel" in kw else {})


def test_the_gain_separates_the_groups():
    """Gain sets the electrons→ADU conversion: a dark at gain 100 corrects nothing at 300."""
    groups = group_frames([frame_gain(100, "dark"), frame_gain(300, "dark")])

    assert len(groups) == 2
    assert {g.gain for g in groups} == {100, 300}


def test_a_dark_of_another_gain_is_never_matched():
    """Dual-gain rigs (narrowband at high gain, RGB at low gain) are common."""
    frames = [frame_gain(300, "light", filter="Ha"),
              frame_gain(100, "dark"), frame_gain(300, "dark")]
    groups = group_frames(frames)
    target = next(g for g in groups if g.kind == "light")

    assert match_calibration(groups)[target.key].dark.gain == 300


def test_an_unknown_gain_stays_compatible():
    """Lacking the information, better to match than to refuse outright."""
    assert len(group_frames([frame_gain(None, "dark"), frame_gain(100, "dark")])) == 1


def test_the_gain_appears_in_the_key():
    group = group_frames([frame_gain(100, "bias")])[0]

    assert "g100" in group.key


def test_two_telescopes_do_not_share_their_flats():
    """Same camera, different optics: the frames are indistinguishable by geometry."""
    groups = group_frames([frame_gain(100, "flat", filter="L", tel="T80"),
                            frame_gain(100, "flat", filter="L", tel="RC8")])

    assert len(groups) == 2


def test_colliding_keys_are_disambiguated():
    """The key names the master file: two homonyms would overwrite each other."""
    groups = group_frames([frame_gain(100, "flat", filter="L", tel="T80"),
                            frame_gain(100, "flat", filter="L", tel="RC8")])

    assert len({g.key for g in groups}) == 2
    assert {g.discriminator for g in groups} == {"T80", "RC8"}


def test_a_single_rig_keeps_readable_keys():
    """Only the groups that actually collide get a suffix."""
    groups = group_frames([frame_gain(100, "flat", filter="L", tel="T80"),
                            frame_gain(100, "flat", filter="L", tel="T80")])

    assert len(groups) == 1
    assert groups[0].discriminator == ""
    assert groups[0].key == "flat_L_bin1_g100_m10C"


def test_a_frame_without_a_rig_keyword_stays_compatible():
    """Requiring the keyword would rule out healthy sets where only some frames carry it."""
    groups = group_frames([frame_gain(100, "dark", tel="T80"), frame_gain(100, "dark")])

    assert len(groups) == 1


def test_the_rig_survives_serialization():
    group = group_frames([frame_gain(100, "flat", filter="L", tel="T80")])[0]
    reread = FrameGroup.from_dict(group.to_dict())

    assert reread.extra == {"TELESCOP": "T80"}
    assert reread.gain == 100
    assert reread.key == group.key


def test_the_scan_captures_the_rig_identity(raws_mono):
    inventory = scan(raws_mono)

    assert all(f.extra.get("INSTRUME") == "Retina Synthetic" for f in inventory)
    # and it survives the RPC transport
    from retina.pipeline.scan import Inventory

    reread = Inventory.from_dict(inventory.to_dict())
    assert reread.frames[0].extra == inventory.frames[0].extra


# --- mosaic panels ----------------------------------------------------------------------
#
# A smart telescope in "framing mode" sweeps several pointings: nothing else tells those
# exposures apart, and without detection they all land in a single group that registration
# cannot stack.

def pointed(ra: float, dec: float, *, name: str = "p", kind: str = "light") -> FrameInfo:
    return FrameInfo(path=f"/data/{name}.fits", kind=kind, filter="L", exposure=300.0,
                     binning=1, temperature=-10.0, width=100, height=100, ra=ra, dec=dec)


def test_a_single_pointing_changes_nothing_in_the_keys():
    """Non-regression: the common case must neither suffix nor split anything."""
    groups = group_frames([pointed(10.68, 41.26, name="a"), pointed(10.69, 41.27, name="b")])

    assert len(groups) == 1
    assert groups[0].panel == 0
    assert groups[0].key == "light_L_300s_bin1_m10C"


def test_two_panels_yield_two_light_groups():
    groups = group_frames([pointed(10.0, 41.0, name="a1"), pointed(10.005, 41.002, name="a2"),
                            pointed(11.5, 41.0, name="b1"), pointed(11.505, 41.001, name="b2")])

    assert len(groups) == 2
    assert {g.key for g in groups} == {"light_L_300s_bin1_m10C_panel1",
                                        "light_L_300s_bin1_m10C_panel2"}
    assert all(len(g) == 2 for g in groups)


def test_panels_are_numbered_deterministically():
    """The key names a file: the discovery order cannot be what decides it."""
    frames = [pointed(10.0, 41.0, name="a"), pointed(11.5, 41.0, name="b"),
              pointed(10.0, 42.0, name="c")]
    expected = {g.key: sorted(g.paths) for g in group_frames(frames)}

    for order in ([2, 0, 1], [1, 2, 0], [0, 2, 1]):
        other = group_frames([frames[i] for i in order])
        assert {g.key: sorted(g.paths) for g in other} == expected

    # numbered by increasing (declination, right ascension)
    numbers = {g.frames[0].name: g.panel for g in group_frames(frames)}
    assert numbers == {"a.fits": 1, "b.fits": 2, "c.fits": 3}


def test_the_separation_accounts_for_declination():
    """1° of right ascension is worth no more than 10′ on the sky at δ = 80°."""
    from retina.pipeline.groups import angular_separation

    assert angular_separation(10.0, 80.0, 11.0, 80.0) == pytest.approx(0.1736, abs=1e-3)
    # comparing raw RA here would make two panels where there is only one
    close = group_frames([pointed(10.0, 80.0, name="a"), pointed(11.0, 80.0, name="b")])
    assert len(close) == 1

    # at the equator, the same RA gap really does separate two panels
    apart = group_frames([pointed(10.0, 0.0, name="a"), pointed(11.0, 0.0, name="b")])
    assert len(apart) == 2


def test_crossing_zero_hours_does_not_fabricate_a_panel():
    """359.95° and 0.05° are 6′ apart, not 360° apart."""
    groups = group_frames([pointed(359.95, 0.0, name="a"), pointed(0.05, 0.0, name="b")])

    assert len(groups) == 1


def test_a_missing_pointing_breaks_nothing():
    """A set with no RA/DEC must group exactly as it did before."""
    groups = group_frames([frame("light", filter="L", expo=300.0, name="a"),
                            frame("light", filter="L", expo=300.0, name="b")])

    assert len(groups) == 1
    assert groups[0].panel == 0
    assert (groups[0].ra, groups[0].dec) == (None, None)


def test_darks_and_flats_are_never_split_by_the_pointing():
    """The shutter is closed, or the mount faces a light panel: it makes no sense."""
    frames = [pointed(10.0, 41.0, name="d1", kind="dark"),
              pointed(30.0, 10.0, name="d2", kind="dark"),
              pointed(10.0, 41.0, name="f1", kind="flat"),
              pointed(30.0, 10.0, name="f2", kind="flat")]

    groups = group_frames(frames)

    assert sorted(g.kind for g in groups) == ["dark", "flat"]
    assert all(g.panel == 0 for g in groups)


def test_the_panel_adds_up_with_the_filter():
    """A mosaic's layers must line up panel by panel."""
    frames = []
    for filter in ("L", "Ha"):
        for i, ra in enumerate((10.0, 11.5)):
            f = pointed(ra, 41.0, name=f"{filter}{i}")
            f.filter = filter
            frames.append(f)

    groups = group_frames(frames)

    assert len(groups) == 4
    # the same panel carries the same number across every filter
    by_number = {(g.filter, g.panel) for g in groups}
    assert by_number == {("L", 1), ("L", 2), ("Ha", 1), ("Ha", 2)}


def test_a_light_without_a_pointing_joins_no_panel():
    """Do not file it at random: its panel is unknown, and its key says so."""
    orphan = frame("light", filter="L", expo=300.0, name="orphan")
    groups = group_frames([pointed(10.0, 41.0, name="a"), pointed(11.5, 41.0, name="b"),
                            orphan])

    panel_less = [g for g in groups if g.panel == 0]
    assert len(panel_less) == 1
    assert panel_less[0].paths == [orphan.path]


def test_the_group_states_the_center_of_its_panel():
    """That is what a mosaic step needs in order to place the panels."""
    groups = group_frames([pointed(10.0, 41.0, name="a"), pointed(10.02, 41.02, name="b")])

    ra, dec = groups[0].pointing
    assert ra == pytest.approx(10.01, abs=1e-3)
    assert dec == pytest.approx(41.01, abs=1e-3)


def test_the_panel_and_the_pointing_survive_the_transport():
    group = group_frames([pointed(10.0, 41.0, name="a"), pointed(11.5, 41.0, name="b")])[0]
    data = group.to_dict()
    reread = FrameGroup.from_dict(data)

    assert data["panel"] == 1
    assert (reread.panel, reread.key) == (group.panel, group.key)
    assert reread.pointing == pytest.approx(group.pointing)


def test_the_separation_threshold_is_adjustable():
    frames = [pointed(10.0, 41.0, name="a"), pointed(10.4, 41.0, name="b")]

    assert len(group_frames(frames)) == 2                            # 0.30° > 0.25°
    assert len(group_frames(frames, panel_separation=1.0)) == 1


def test_a_continuous_drift_stays_a_single_panel():
    """Single linkage: a panel spreads out by drifting, not by jumping."""
    frames = [pointed(10.0 + 0.2 * i, 41.0, name=f"d{i}") for i in range(6)]

    assert len(group_frames(frames)) == 1


def test_the_framing_set_yields_two_panels(raws_framing):
    """End to end: sexagesimal headers → detection → group keys."""
    from retina.pipeline.synthetic import truth

    inventory = scan(raws_framing)
    groups = inventory.groups()

    assert key(groups, "light") == ["light_5s_bin1_g120_m10C_panel1",
                                     "light_5s_bin1_g120_m10C_panel2"]
    # the calibration, on the other hand, stays shared by both panels
    assert len(key(groups, "dark")) == 1
    assert len(key(groups, "flat")) == 1

    lights = sorted((g for g in groups if g.kind == "light"), key=lambda g: g.panel)
    for group, (ra, dec) in zip(lights, truth("framing")["panels"], strict=True):
        assert len(group) == 4
        assert group.ra == pytest.approx(ra, abs=0.01)
        assert group.dec == pytest.approx(dec, abs=0.01)


def test_each_panel_receives_the_same_masters(raws_framing):
    """Splitting the panels must not deprive one of them of its calibration."""
    groups = scan(raws_framing).groups()
    matches = match_calibration(groups)

    lights = [m for k, m in matches.items() if k.startswith("light")]
    assert len(lights) == 2
    assert len({m.dark.key for m in lights}) == 1
    assert all(m.flat is not None for m in lights)


# --- survey (grouping + matching) -----------------------------------------------------
#
# What the wizard shows per group. The computation lives here, in the domain: the frontend
# used to approximate the grouping on its side, and so displayed keys the plan never used.

def test_the_survey_brings_together_groups_and_matching():
    inventory = Inventory(root="/data", frames=[
        frame("light", filter="L", expo=300.0),
        frame("flat", filter="L", expo=2.0),
        frame("bias", expo=0.0),
    ])

    state = survey(inventory)

    assert {g.kind for g in state.groups} == {"light", "flat", "bias"}
    target = next(g for g in state.groups if g.kind == "light")
    assert state.matches[target.key].flat is not None


def test_the_survey_says_what_is_missing():
    """A light with no flat must show on its row — that is what ruins a night."""
    inventory = Inventory(root="/data", frames=[frame("light", filter="L", expo=300.0)])

    state = survey(inventory)
    match = state.matches[state.groups[0].key]

    assert (match.bias, match.dark, match.flat) == (None, None, None)
    assert match.is_empty


def test_the_survey_serializes_for_the_transport():
    inventory = Inventory(root="/data", frames=[
        frame("light", filter="L", expo=300.0), frame("flat", filter="L", expo=2.0)])

    data = survey(inventory).to_dict()

    key = next(g["key"] for g in data["groups"] if g["kind"] == "light")
    assert data["matches"][key]["flat"] is not None
    # the groups travel whole: they go back as they are to `plan(groups=…)`
    assert FrameGroup.from_dict(data["groups"][0]).key == data["groups"][0]["key"]


def test_the_survey_ignores_the_frames_set_aside():
    lights = frame("light", filter="L", expo=300.0)
    flat = frame("flat", filter="L", expo=2.0)
    flat.excluded = True

    state = survey(Inventory(root="/data", frames=[lights, flat]))

    assert [g.kind for g in state.groups] == ["light"]
    assert state.matches[state.groups[0].key].flat is None


# --- calibration chain -----------------------------------------------------------------
#
# What the GUI draws. The formula lives in the domain: which masters take part, and in what
# order, is an astronomy decision — drawing it is rendering.

def test_the_chain_follows_the_image_calibration_formula():
    """(target - bias - k·dark) / flat: the order is not decorative."""
    m = match_for([frame("light", filter="L", expo=300.0), frame("dark", expo=300.0),
                   frame("flat", filter="L", expo=1.0), frame("bias", expo=0.0)])

    assert [(e.op, e.role) for e in m.chain] == [("subtract", "dark"), ("divide", "flat")]


def test_the_chain_states_the_scale_and_the_dark_current():
    """A scaled dark is debiased first: the chain has to show it."""
    m = match_for([frame("light", filter="L", expo=150.0), frame("dark", expo=300.0),
                   frame("bias", expo=0.0)])

    dark = next(e for e in m.chain if e.role == "dark")
    assert dark.scale == pytest.approx(0.5)
    assert dark.derived is not None  # the bias whose contribution is taken out


def test_a_dark_of_the_exact_exposure_derives_from_nothing():
    m = match_for([frame("light", filter="L", expo=300.0), frame("dark", expo=300.0),
                   frame("bias", expo=0.0)])

    assert next(e for e in m.chain if e.role == "dark").derived is None


def test_a_group_without_masters_has_an_empty_chain():
    m = match_for([frame("light", filter="L", expo=300.0)])

    assert m.chain == []
    assert m.is_empty


def test_the_chain_survives_the_transport():
    m = match_for([frame("light", filter="L", expo=150.0), frame("dark", expo=300.0),
                   frame("bias", expo=0.0)])

    text_value = m.to_dict()["chain"]

    assert [e["role"] for e in text_value] == ["bias", "dark"]
    assert text_value[1]["scale"] == pytest.approx(0.5)
