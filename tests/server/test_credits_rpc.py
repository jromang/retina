"""Credits seen from the network — the licences page is one more client, not a source."""

from __future__ import annotations


async def test_the_list_arrives_grouped_with_its_summary(session):
    await session.call("hello")

    payload = await session.call("credits.list")

    assert payload["kinds"] == ["asset", "frontend", "native", "python", "download"]
    assert len(payload["components"]) > 20
    assert sum(payload["summary"].values()) == len(payload["components"])
    for component in payload["components"]:
        assert {"id", "name", "kind", "license"} <= set(component)


async def test_a_full_notice_can_be_retrieved(session):
    await session.call("hello")

    text = await session.call("credits.notice", id="tabler-icons")

    assert "MIT" in text and "Paweł Kuna" in text


async def test_a_missing_notice_becomes_a_clean_error(session):
    from rpcsession import RpcFailure

    await session.call("hello")

    try:
        await session.call("credits.notice", id="dockview-core")
    except RpcFailure as failure:
        assert "notice" in str(failure)
    else:
        raise AssertionError("a component without a notice must raise")


async def test_the_ai_models_are_flagged_as_non_commercial(session):
    """The starting point: the user cannot guess that a model restricts them."""
    await session.call("hello")

    payload = await session.call("credits.list")

    graxpert = next(c for c in payload["components"] if c["id"] == "graxpert-models")
    assert "NC" in graxpert["license"]
    assert graxpert["kind"] == "download"
