"""The mask over the wire: the six RPCs, the echo, and what the snapshot publishes of it.

Mask rendering lives on the WebGL side, but what it renders comes from here: without `mask`
in the snapshot and without `mask_visible` in the viewport sub-object, the client would know
neither that there is a mask, nor whether it should show it. So these tests pin down the
published shape as much as the delegation.
"""

from __future__ import annotations

import numpy as np
import pytest
from retina.model.image import Image
from rpcsession import RpcFailure


def _half_mask(width: int = 24, height: int = 16) -> Image:
    """Left half white, right half black — the most legible shape on screen."""
    m = np.zeros((height, width, 1), dtype=np.float32)
    m[:, : width // 2, :] = 1.0
    return Image(m)


async def test_an_absent_mask_publishes_nothing(session):
    await session.call("hello")
    snapshot = await session.call("state.snapshot")
    assert snapshot["windows"][0]["mask"] is None


async def test_set_mask_publishes_geometry_and_generation(session, domain):
    domain.new_window(_half_mask(), window_id="Mask")
    await session.call("hello")
    await session.call("app.set_mask", source="Mask", window="Test01")

    snapshot = await session.call("state.snapshot")
    win = next(w for w in snapshot["windows"] if w["id"] == "Test01")
    assert win["mask"] == {
        "enabled": True,
        "inverted": False,
        "width": 24,
        "height": 16,
        "channels": 1,
        "gen": win["mask"]["gen"],
    }
    assert win["mask"]["gen"] >= 1, "without a generation, the client cannot version its URL"


async def test_visible_and_enabled_are_two_distinct_fields(session, domain):
    """`enabled` governs the processes, `mask_visible` the display — two places, on purpose."""
    domain.new_window(_half_mask(), window_id="Mask")
    await session.call("hello")
    await session.call("app.set_mask", source="Mask", window="Test01")
    await session.call("app.set_mask_visible", visible=False, window="Test01")
    await session.call("app.set_mask_enabled", enabled=False, window="Test01")

    win = next(w for w in (await session.call("state.snapshot"))["windows"] if w["id"] == "Test01")
    assert win["mask"]["enabled"] is False
    assert win["viewport"]["mask_visible"] is False
    target = next(w for w in domain.windows if w.id == "Test01")
    assert target.mask_enabled is False
    assert target.viewport.mask_visible is False


async def test_mask_visible_is_echoed_and_rebroadcast(session, domain):
    await session.call("hello")
    session.clear()
    await session.call("app.set_mask_visible", visible=False)
    await session.drain()

    assert "app.set_mask_visible(False)" in [p["code"] for p in session.of("echo")]
    assert session.of("state.changed"), "the display changed: the client must be told"


async def test_the_ten_display_modes_get_through(session, domain):
    modes = [
        "replace", "multiply", "overlay_red", "overlay_green", "overlay_blue",
        "overlay_yellow", "overlay_magenta", "overlay_cyan", "overlay_orange",
        "overlay_violet",
    ]
    await session.call("hello")
    for mode in modes:
        await session.call("app.set_mask_display_mode", mode=mode)
        snapshot = await session.call("state.snapshot")
        assert snapshot["windows"][0]["viewport"]["mask_display_mode"] == mode


async def test_an_unknown_mode_lists_the_accepted_values(session):
    await session.call("hello")
    with pytest.raises(RpcFailure) as err:
        await session.call("app.set_mask_display_mode", mode="overlay_pink")
    assert "overlay_red" in str(err.value)


async def test_inversion_does_not_change_the_generation(session, domain):
    """Inversion is a display toggle: re-uploading the texture would be pure waste.

    The shader inverts on its own (as `mask_array` does on the process side); if `gen` moved,
    the client would refetch a few megabytes on every click of the "inverted" checkbox.
    """
    domain.new_window(_half_mask(), window_id="Mask")
    await session.call("hello")
    await session.call("app.set_mask", source="Mask", window="Test01")
    before = next(
        w for w in (await session.call("state.snapshot"))["windows"] if w["id"] == "Test01"
    )["mask"]["gen"]

    await session.call("app.set_mask_inverted", inverted=True, window="Test01")
    after = next(
        w for w in (await session.call("state.snapshot"))["windows"] if w["id"] == "Test01"
    )["mask"]
    assert after["inverted"] is True
    assert after["gen"] == before


async def test_remove_mask_goes_back_to_null(session, domain):
    domain.new_window(_half_mask(), window_id="Mask")
    await session.call("hello")
    await session.call("app.set_mask", source="Mask", window="Test01")
    await session.call("app.remove_mask", window="Test01")

    win = next(w for w in (await session.call("state.snapshot"))["windows"] if w["id"] == "Test01")
    assert win["mask"] is None
