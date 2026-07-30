"""``process.run_container`` — a recipe executed as a whole.

What this test really protects: **the order**. Dropping a recipe used to launch one job per
step onto a pool of four threads; nothing guaranteed the sequence, and the order is the very
meaning of a pipeline. So we check on two non-commuting processes, not merely that "it runs".
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from retina.model.image import Image
from retina.process.container import ProcessContainer
from retina.process.registry import get
from rpcsession import RpcFailure


async def _wait_job(session, timeout: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        for method in ("job.done", "job.error", "job.cancelled"):
            events = session.of(method)
            if events:
                return {"method": method, **events[-1]}
        await asyncio.sleep(0.05)
    raise AssertionError(f"no job completion within {timeout}s: {session.notifications}")


#: Two operations that do **not** commute. The choice matters: `Invert` and `Rescale` are both
#: affine, so they commute — a first draft picked them, and the test passed whatever the real
#: execution order was. Blurring then thresholding, on the other hand, has nothing to do with
#: thresholding then blurring.
RECIPE = [
    {"process_id": "GaussianConvolution", "values": {"sigma": 2.0}},
    {"process_id": "Binarize", "values": {"threshold": 0.4}},
]


async def test_the_recipe_produces_the_same_pixels_as_the_console(session, domain):
    """Parity: the same container over the network and from the console, bit for bit."""
    await session.call("hello")
    expected = ProcessContainer(
        [get(step["process_id"])(**step["values"]) for step in RECIPE]
    ).execute_on_image(domain.active_view.image)

    await session.call("process.run_container", processes=RECIPE)
    outcome = await _wait_job(session)
    assert outcome["method"] == "job.done", outcome

    np.testing.assert_allclose(domain.active_view.image.data, expected.data, atol=1e-6)


async def test_the_recipe_runs_in_order(session, domain):
    """A single job, hence a sequence — and the reverse order does give something else."""
    await session.call("hello")
    start = domain.active_view.image.copy()
    reversed_result = ProcessContainer(
        [get(step["process_id"])(**step["values"]) for step in reversed(RECIPE)]
    ).execute_on_image(start)

    await session.call("process.run_container", processes=RECIPE)
    await _wait_job(session)

    assert not np.allclose(domain.active_view.image.data, reversed_result.data, atol=1e-6)


async def test_a_single_job_for_the_whole_recipe(session):
    """That is the very point of the method: N steps, one job, one echo."""
    await session.call("hello")
    session.clear()
    result = await session.call("process.run_container", processes=RECIPE)
    assert result["job"].startswith("j")
    await _wait_job(session)

    assert len(session.of("job.started")) == 1
    echoes = [e["code"] for e in session.of("echo")]
    assert len(echoes) == 1, echoes
    assert "ProcessContainer" in echoes[0]


async def test_each_step_leaves_its_history_entry(session, domain):
    """A recipe is not an opaque operation: it must be undoable step by step."""
    await session.call("hello")
    before = len(domain.active_view.history_labels())

    await session.call("process.run_container", processes=RECIPE)
    await _wait_job(session)

    assert len(domain.active_view.history_labels()) == before + len(RECIPE)


async def test_an_empty_recipe_is_refused(session):
    with pytest.raises(RpcFailure):
        await session.call("process.run_container", processes=[])


async def test_an_unknown_process_is_refused_before_starting(session, domain):
    before = domain.active_view.image.data.copy()
    with pytest.raises(RpcFailure) as error:
        await session.call(
            "process.run_container",
            processes=[{"process_id": "Invert", "values": {}},
                       {"process_id": "DoesNotExist", "values": {}}],
        )
    assert "unreadable" in str(error.value)
    # Nothing was applied: refusing mid-recipe would leave the image half processed.
    np.testing.assert_array_equal(domain.active_view.image.data, before)


async def test_a_global_process_is_refused(session):
    """`execute_on` would fail midway, after having already modified the image."""
    with pytest.raises(RpcFailure) as error:
        await session.call(
            "process.run_container",
            processes=[{"process_id": "Invert", "values": {}},
                       {"process_id": "Integration", "values": {}}],
        )
    assert "global" in str(error.value)


async def test_without_an_active_view_the_refusal_is_immediate(session, domain):
    """An RPC error right away rather than a job that starts only to fail a second later."""
    for window in list(domain.windows):
        domain.close_window(window)
    with pytest.raises(RpcFailure) as error:
        await session.call("process.run_container", processes=RECIPE)
    assert "target view" in str(error.value)


# --- step flags (parity with the reference implementation) ----------------------
async def test_a_disabled_step_is_not_executed(session, domain):
    """The classic gesture: try the recipe without one step, without losing it."""
    await session.call("hello")
    start = domain.active_view.image.copy()
    expected = get("Binarize")(threshold=0.4).execute_on_image(start)

    recipe = [dict(RECIPE[0], enabled=False), RECIPE[1]]
    await session.call("process.run_container", processes=recipe)
    outcome = await _wait_job(session)
    assert outcome["method"] == "job.done", outcome

    np.testing.assert_allclose(domain.active_view.image.data, expected.data, atol=1e-6)
    # A single history entry: the skipped step pushes none.
    assert len(domain.active_view.history_labels()) == 2


async def test_a_disabled_global_process_no_longer_blocks(session):
    """It will not run: refusing it would mean forbidding to disable what gets in the way."""
    await session.call("hello")
    await session.call(
        "process.run_container",
        processes=[
            {"process_id": "Invert", "values": {}},
            {"process_id": "Integration", "values": {}, "enabled": False},
        ],
    )
    assert (await _wait_job(session))["method"] == "job.done"


async def test_the_flags_survive_the_library(session):
    """`library.get` must return what `library.put` received, flags included."""
    recipe = [
        dict(RECIPE[0], enabled=False),
        dict(RECIPE[1], mask="Test01", mask_inverted=True),
    ]
    await session.call("library.put", name="e2e-flags", processes=recipe)
    reread = await session.call("library.get", name="e2e-flags")

    assert reread["kind"] == "container"
    assert reread["processes"][0]["enabled"] is False
    assert reread["processes"][1]["mask"] == "Test01"
    assert reread["processes"][1]["mask_inverted"] is True
    await session.call("library.delete", name="e2e-flags")


async def test_a_single_masked_process_stays_a_recipe(session):
    """Downgrading it to an instance would lose its mask — this is the edge case of the
    "one process = one instance" shortcut."""
    await session.call(
        "library.put",
        name="e2e-solo-mask",
        processes=[{"process_id": "Invert", "values": {}, "mask": "Test01"}],
    )
    reread = await session.call("library.get", name="e2e-solo-mask")
    assert reread["kind"] == "container"
    assert reread["processes"][0]["mask"] == "Test01"
    await session.call("library.delete", name="e2e-solo-mask")


async def test_an_ordinary_recipe_keeps_its_wire_shape(session):
    """No new key on a flagless recipe: clients that ignore them keep reading it as is."""
    await session.call("library.put", name="e2e-simple", processes=RECIPE)
    reread = await session.call("library.get", name="e2e-simple")
    assert set(reread["processes"][0]) == {"process_id", "values"}
    await session.call("library.delete", name="e2e-simple")


async def test_the_mask_of_a_step_limits_its_effect(session, domain):
    """End to end: the mask named by view id is resolved at execution time."""
    await session.call("hello")
    height, width = domain.active_view.image.data.shape[:2]
    half = np.zeros((height, width, 1), dtype=np.float32)
    half[:, width // 2 :, :] = 1.0
    domain.new_window(Image(half), window_id="Mask01")
    start = domain.view("Test01").image.data.copy()

    await session.call(
        "process.run_container",
        processes=[{"process_id": "Invert", "values": {}, "mask": "Mask01"}],
        view="Test01",
    )
    assert (await _wait_job(session))["method"] == "job.done"

    actual = domain.view("Test01").image.data
    np.testing.assert_allclose(actual[:, : width // 2], start[:, : width // 2], atol=1e-6)
    np.testing.assert_allclose(
        actual[:, width // 2 :], 1.0 - start[:, width // 2 :], atol=1e-6
    )
    # And the window did not keep the step's mask.
    assert domain.view("Test01").window.mask is None


async def test_a_mask_that_cannot_be_found_is_reported(session):
    """Silently applying without a mask would touch the whole image, when restricting it was
    precisely the point."""
    await session.call("hello")
    await session.call(
        "process.run_container",
        processes=[{"process_id": "Invert", "values": {}, "mask": "DoesNotExist"}],
    )
    outcome = await _wait_job(session)
    assert outcome["method"] == "job.error"
    assert "Mask not found" in outcome["message"]
