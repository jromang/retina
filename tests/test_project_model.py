"""Model serialisation primitives — the bricks the project format depends on.

Tested here, separately from the format, because they *also* serve the snapshot: a divergence
between the two would teach the client two shapes of the same data.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina import STF, ChannelSTF, Image
from retina.model.view import HistoryEntry, View
from retina.model.viewport_state import (
    DISPLAY_CHANNELS,
    InteractionMode,
    MaskDisplayMode,
    ReadoutOptions,
    TransparencyMode,
    ViewportState,
)
from retina.process.unknown import UnknownProcess, process_from_dict


def _image(h: int = 8, w: int = 6, c: int = 1) -> Image:
    return Image(np.linspace(0, 1, h * w * c, dtype=np.float32).reshape(h, w, c))


# --- STF -------------------------------------------------------------------------------

def test_stf_round_trip():
    stf = STF([ChannelSTF(0.01, 0.3, 0.9), ChannelSTF(0.02, 0.4, 0.95)])

    reread = STF.from_dict(stf.to_dict())

    assert len(reread.channels) == 2
    assert reread.channels[1].midtones == pytest.approx(0.4)
    assert reread.to_dict() == stf.to_dict()


def test_an_stf_without_channels_keeps_a_default_channel():
    """An `STF(channels=[])` would break `apply` on the very first image."""
    assert len(STF.from_dict({"channels": []}).channels) == 1


def test_the_repr_of_an_stf_is_replayable():
    """`app.set_stf` echoes `app.set_stf({stf!r})`: if the repr is not valid Python, the echo
    promises code that cannot be pasted back into the console."""
    stf = STF([ChannelSTF(0.01, 0.3, 0.9)])

    rebuilt = eval(repr(stf), {"STF": STF, "ChannelSTF": ChannelSTF})

    assert rebuilt.to_dict() == stf.to_dict()


def test_the_snapshot_and_the_project_speak_the_same_language():
    from retina.server.state import SnapshotBuilder

    view = View(_image(), "V")
    view.stf = STF([ChannelSTF(0.01, 0.3, 0.9)])

    assert SnapshotBuilder._stf(view)["channels"] == view.stf.to_dict()["channels"]


# --- ViewportState ---------------------------------------------------------------------

def test_full_viewport_round_trip():
    vp = ViewportState((100, 80))
    vp.set_viewport((12.5, 34.25), zoom=4.0)
    vp.set_display_channel("cie_a")
    vp.set_interaction_mode(InteractionMode.DYNAMIC)
    vp.set_mask_display_mode(MaskDisplayMode.OVERLAY_CYAN)
    vp.set_mask_visible(False)
    vp.set_transparency_mode(TransparencyMode.COLOR)
    vp.set_stf_enabled(False)
    vp.readout = ReadoutOptions(probe_size=5, color_space="cielab", real=False,
                                precision=2, show_loupe=False)
    vp.set_overlays("tool", [{"kind": "markers", "points": [(1, 2)], "color": (1, 0, 0, 1)}])
    expected = vp.to_dict()

    fresh = ViewportState((100, 80))
    fresh.apply_dict(expected)

    assert fresh.to_dict() == expected


def test_the_device_geometry_is_not_serialised():
    """vw/vh/dpr describe today's widget, not a setting: restoring them would impose
    yesterday's dimensions, which the first `update_geometry` would overwrite."""
    vp = ViewportState((100, 80))
    vp.set_geometry(1920, 1080, 2.0)

    rendered = vp.to_dict()

    assert {"vw", "vh", "dpr"}.isdisjoint(rendered)
    fresh = ViewportState((100, 80))
    fresh.set_geometry(640, 480, 1.0)
    fresh.apply_dict(rendered)
    assert (fresh.vw, fresh.vh, fresh.dpr) == (640.0, 480.0, 1.0)


def test_apply_dict_ignores_values_from_a_newer_retina():
    """An unknown channel or mode must not fail the opening of a whole project: we keep the
    value in place and carry on."""
    vp = ViewportState((100, 80))
    vp.set_display_channel("red")

    vp.apply_dict({"channel": "future_channel", "interaction_mode": "future_mode",
                   "zoom": 2.0})

    assert vp.display_channel == "red"
    assert vp.interaction_mode is InteractionMode.READOUT
    assert vp.zoom == pytest.approx(2.0)


def test_apply_dict_notifies_only_once():
    """Setting ten fields in ten notifications means ten viewport re-renders."""
    vp = ViewportState((100, 80))
    calls = []
    vp.on_change = lambda: calls.append(1)

    vp.apply_dict(ViewportState((100, 80)).to_dict())

    assert len(calls) == 1


def test_apply_dict_clamps_the_zoom():
    vp = ViewportState((100, 80))
    vp.apply_dict({"zoom": 1e6})
    assert vp.zoom == pytest.approx(64.0)


def test_to_dict_covers_every_display_channel():
    """Guard rail: a channel added tomorrow must stay restorable."""
    for channel in DISPLAY_CHANNELS:
        vp = ViewportState((10, 10))
        vp.set_display_channel(channel)
        fresh = ViewportState((10, 10))
        fresh.apply_dict(vp.to_dict())
        assert fresh.display_channel == channel


# --- restore_history -------------------------------------------------------------------

def test_restore_history_puts_back_the_current_image():
    a, b, c = _image(), _image(), _image()
    view = View(a, "V")

    view.restore_history([HistoryEntry("initial", a), HistoryEntry("Invert", b),
                          HistoryEntry("Rescale", c)], index=1)

    assert view.history_index == 1
    assert view.image is b            # the object itself, not a copy
    assert view.can_go_backward and view.can_go_forward
    assert view.history_labels() == ["initial", "Invert", "Rescale"]


def test_restore_history_keeps_the_redo_entries():
    """Saving in the middle of an undo then reopening must leave redo possible — that is what
    embedding the swap files in the project buys."""
    a, b, c = _image(), _image(), _image()
    view = View(a, "V")
    view.restore_history([HistoryEntry("initial", a), HistoryEntry("A", b),
                          HistoryEntry("B", c)], index=1)

    assert view.redo() is True
    assert view.image is c


def test_restore_history_refuses_an_empty_history_or_an_out_of_range_index():
    view = View(_image(), "V")
    with pytest.raises(ValueError):
        view.restore_history([], 0)
    with pytest.raises(ValueError):
        view.restore_history([HistoryEntry("initial", _image())], 3)


def test_restore_history_purges_a_bracket_in_progress():
    """A `begin_process` left open would apply its label to the first entry pushed after
    restoration — a label from the old world on a state from the new one."""
    view = View(_image(), "V")
    view.begin_process("In progress", process=object())

    view.restore_history([HistoryEntry("initial", _image())], 0)
    view.end_process()

    assert view.history_labels() == ["initial", "process"]


# --- UnknownProcess --------------------------------------------------------------------

def test_unknown_process_keeps_the_dict_identical():
    """Re-saving on a machine without the plugin must lose nothing, otherwise a temporary
    absence would become a permanent loss."""
    data = {"process_id": "ExoticPlugin", "values": {"sigma": 2.5, "mode": "soft"}}

    unknown = process_from_dict(data)

    assert isinstance(unknown, UnknownProcess)
    assert unknown.to_dict() == data
    assert unknown.process_id == "ExoticPlugin"


def test_unknown_process_refuses_to_run_and_names_what_is_missing():
    unknown = UnknownProcess({"process_id": "ExoticPlugin", "values": {}})

    with pytest.raises(RuntimeError, match="ExoticPlugin"):
        unknown.execute_on(object())
    assert "ExoticPlugin" in unknown.to_python_source()
    assert unknown.to_python_source().lstrip().startswith("#")


def test_process_from_dict_returns_the_real_instance_when_it_exists():
    from retina.process.registry import load_builtin

    load_builtin()
    instance = process_from_dict({"process_id": "Invert", "values": {}})

    assert not isinstance(instance, UnknownProcess)
    assert instance.process_id == "Invert"


def test_process_from_dict_also_degrades_on_a_vanished_parameter():
    """An older project may name a parameter the process no longer has: that is a TypeError,
    not a KeyError, and it must not take the opening down either."""
    from retina.process.registry import load_builtin

    load_builtin()
    instance = process_from_dict({"process_id": "Invert",
                                  "values": {"vanished_parameter": 1}})

    assert isinstance(instance, UnknownProcess)
    assert instance.to_dict()["values"] == {"vanished_parameter": 1}
