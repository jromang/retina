"""Recipe from history, an instance's source code, XML export/import.

Three capabilities the domain has had since day one — ``View.recipe()``,
``Process.to_python_source()``, ``ProcessContainer.to_xml()`` — and that nothing exposed. So
reproducibility, pillar no. 4, stopped at the console: the reference application builds a
ProcessContainer from its history explorer and puts an "Instance Source Code" button on
*every* process interface.
"""

from __future__ import annotations

import pytest
from rpcsession import RpcFailure


async def test_the_recipe_picks_up_the_views_history(session, domain):
    await session.call("hello")
    await session.call("process.run", process_id="Invert", params={})
    await session.call("process.run", process_id="Binarize", params={"threshold": 0.3})
    # Jobs are asynchronous: wait until the history is populated.
    for _ in range(200):
        if len(domain.active_view.history_labels()) >= 3:
            break
        await session.drain(0.05)

    recipe = await session.call("app.recipe")
    assert [step["process_id"] for step in recipe] == ["Invert", "Binarize"]
    assert recipe[1]["values"]["threshold"] == 0.3


async def test_the_recipe_of_a_fresh_view_is_empty(session):
    """No error: a view with no processing has an empty recipe, and that is an answer."""
    await session.call("hello")
    assert await session.call("app.recipe") == []


async def test_the_recipe_requires_a_view(session, domain):
    for window in list(domain.windows):
        domain.close_window(window)
    with pytest.raises(RpcFailure) as error:
        await session.call("app.recipe")
    assert "target view" in str(error.value)


async def test_the_source_code_of_an_instance_is_runnable(session):
    """What the "Instance Source Code" button must produce: Python you can run again."""
    source = await session.call(
        "app.source", process_id="GaussianConvolution", values={"sigma": 3.5}
    )
    assert "GaussianConvolution(sigma=3.5)" in source
    assert "execute_on(app.active_view)" in source


async def test_an_invalid_parameter_is_refused(session):
    with pytest.raises(RpcFailure) as error:
        await session.call("app.source", process_id="Invert", values={"does_not_exist": 1})
    assert "invalid parameter" in str(error.value)


RECIPE = [
    {"process_id": "Invert", "values": {}, "enabled": False},
    {"process_id": "Binarize", "values": {"threshold": 0.4}, "mask": "Test01"},
]


async def test_the_recipe_reads_back_as_python(session):
    source = await session.call("process.container_source", processes=RECIPE)
    assert "pc.add(Invert())" in source
    assert "pc.disable(0)" in source
    assert "pc.set_mask(1, 'Test01', False)" in source


async def test_xml_round_trip_of_a_recipe(session):
    """The equivalent of the reference application's `.xpsm` files: a recipe must be able to
    go out and come back."""
    xml = await session.call("process.container_xml", processes=RECIPE)
    reread = await session.call("process.container_from_xml", text=xml)
    assert reread == RECIPE


async def test_an_unreadable_xml_is_refused_cleanly(session):
    with pytest.raises(RpcFailure) as error:
        await session.call("process.container_from_xml", text="<not xml at all>")
    assert "unreadable" in str(error.value)
