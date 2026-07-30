"""``project.*`` family — saving and reopening over the network.

The delicate point on the server side: the documents blob (tabs, unsaved buffers,
transcript) lives in the client, and saving has to **ask** it for the blob then wait for it —
without blocking the very loop that is supposed to receive the answer. Three paths are
covered: the client answers, the client stays silent, there is no client at all.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("h5py")

from retina.server.core import ServerApp
from retina.session import SessionStore
from rpcsession import RpcFailure


async def _wait_job(session, timeout: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        for method in ("job.done", "job.error", "job.cancelled"):
            events = session.of(method)
            if events:
                return {"method": method, **events[-1]}
        await asyncio.sleep(0.05)
    raise AssertionError(f"no job ever finished within {timeout}s: {session.notifications}")


async def _wait(session, method: str, timeout: float = 5.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        events = session.of(method)
        if events:
            return events[-1]
        await asyncio.sleep(0.02)
    raise AssertionError(f"{method} never received: {session.notifications}")


@pytest.fixture(autouse=True)
def isolated_session(domain, tmp_path):
    """Each test gets its own recents — otherwise they would hand them around."""
    from retina import i18n

    domain._session = SessionStore(tmp_path / "session.json")
    # The store is swapped in without going through the `app.session` property: that property
    # is what normally registers the preference source with `retina.i18n`.
    i18n.set_preference_source(domain._session.language)
    return domain._session


# --- saving: the three paths of the blob ------------------------------------------------

async def test_the_client_answers_and_its_blob_lands_in_the_file(session, tmp_path):
    from retina.io.project import read_documents

    path = str(tmp_path / "p.retina")
    blob = {"version": 1, "scripts": {"docs": [{"id": "script:1", "text": "x = 1"}]}}

    response = await session.call("project.save", path=path)
    command = await _wait(session, "project.command")
    assert command["op"] == "request_documents"
    await session.call("project.store_documents", request=command["request"], documents=blob)
    finished = await _wait_job(session)

    assert response["job"].startswith("j")
    assert finished["method"] == "job.done"
    assert finished["result"]["path"] == path
    assert read_documents(path) == blob


async def test_a_silent_client_does_not_prevent_saving(domain, tmp_path):
    """A frozen page or a suspended tab must not prevent writing: a project without its
    tabs is worth more than a project never written."""
    from aiohttp.test_utils import TestClient, TestServer
    from retina.io.project import read_documents
    from rpcsession import Session

    server = ServerApp(domain, port=0)
    server.projects._timeout = 0.2  # rather than wait two seconds for nothing
    server.attach()
    path = str(tmp_path / "p.retina")
    try:
        async with (TestClient(TestServer(server.aio)) as client,
                    client.ws_connect(f"/ws?t={server.token}") as ws):
            rpc = Session(ws)
            try:
                await rpc.call("project.save", path=path)
                finished = await _wait_job(rpc)
            finally:
                await rpc.close()
    finally:
        server.detach()

    assert finished["method"] == "job.done"
    assert read_documents(path) is None


async def test_with_no_client_no_request_is_emitted(domain, tmp_path):
    """Headless path (CLI, cron): we rewrite the blob the session already carries."""
    from retina.io.project import read_documents

    server = ServerApp(domain, port=0)
    server.attach()
    domain.set_project_documents({"version": 1, "filesRoot": "/data"})
    path = str(tmp_path / "p.retina")
    try:
        result = server.project_handlers.save(path)
        job = server.runner._jobs[result["job"]]
        job.future.result(timeout=10)
    finally:
        server.detach()

    assert read_documents(path) == {"version": 1, "filesRoot": "/data"}


# --- opening -----------------------------------------------------------------------------

async def test_opening_restores_the_domain_then_pushes_the_documents(session, domain, tmp_path):
    path = str(tmp_path / "p.retina")
    blob = {"version": 1, "scripts": {"docs": [{"id": "script:1", "text": "y = 2"}]}}
    domain.save_project(path, documents=blob)
    domain.close_project()

    await session.call("project.open", path=path)
    finished = await _wait_job(session)
    command = await _wait(session, "project.command")

    assert finished["method"] == "job.done"
    assert finished["result"]["windows"] == ["Test01"]
    assert command["op"] == "restore_documents"
    assert command["documents"] == blob
    assert (await session.call("state.snapshot"))["windows"][0]["id"] == "Test01"


async def test_the_open_report_flags_the_unavailable_processes(session, domain,
                                                               tmp_path, monkeypatch):
    from retina.process import registry
    from retina.processes.channels import Rescale

    Rescale(low=0.1, high=0.9).execute_on(domain.windows[0].main_view)
    path = str(tmp_path / "p.retina")
    domain.save_project(path)

    removed = registry._REGISTRY.pop("Rescale")
    monkeypatch.setattr(registry, "load_builtin", lambda: None)
    try:
        await session.call("project.open", path=path)
        finished = await _wait_job(session)
    finally:
        registry._REGISTRY["Rescale"] = removed

    assert finished["result"]["unknown_processes"] == ["Rescale"]
    # the history stays readable: the step has not vanished from the panel
    view = (await session.call("state.snapshot"))["windows"][0]["views"][0]
    assert view["history"]["labels"] == ["initial", "Rescale"]


# --- guards ------------------------------------------------------------------------------

async def test_a_relative_path_is_rejected(session):
    with pytest.raises(RpcFailure) as exc:
        await session.call("project.save", path="project.retina")
    assert exc.value.code == -32000


async def test_the_suffix_is_filled_in(session, tmp_path):
    await session.call("project.save", path=str(tmp_path / "no_suffix"))
    command = await _wait(session, "project.command")
    await session.call("project.store_documents", request=command["request"], documents=None)
    finished = await _wait_job(session)

    assert finished["result"]["path"].endswith(".retina")


async def test_two_project_operations_do_not_overlap(session, tmp_path):
    """Two writes would aim at the same file, and an open concurrent with a write would
    give a snapshot straddling both."""
    await session.call("project.save", path=str(tmp_path / "p.retina"))

    with pytest.raises(RpcFailure) as exc:
        await session.call("project.save", path=str(tmp_path / "q.retina"))

    assert exc.value.code == -32000
    command = await _wait(session, "project.command")
    await session.call("project.store_documents", request=command["request"], documents=None)
    await _wait_job(session)


async def test_saving_without_a_current_project_nor_a_path_is_rejected(session):
    with pytest.raises(RpcFailure) as exc:
        await session.call("project.save")
    assert exc.value.code == -32000


# --- network / console parity ------------------------------------------------------------

async def test_the_same_domain_gives_the_same_project_over_the_network_and_the_console(
        session, domain, tmp_path):
    """The handler must do nothing but delegate: for equal domain content, the two paths
    produce the same manifest."""
    import json

    import h5py

    from_console = str(tmp_path / "console.retina")
    domain.save_project(from_console)

    from_network = str(tmp_path / "network.retina")
    await session.call("project.save", path=from_network)
    command = await _wait(session, "project.command")
    await session.call("project.store_documents", request=command["request"], documents=None)
    await _wait_job(session)

    def _manifest(path: str) -> dict:
        with h5py.File(path, "r") as file:
            return json.loads(file["manifest"][()])

    assert _manifest(from_console) == _manifest(from_network)


# --- session: hello, recents, reopening ---------------------------------------------------

async def test_the_hello_carries_the_session_state(session):
    hello = await session.call("hello")

    assert set(hello["session"]) >= {"recent_files", "recent_projects", "reopen",
                                     "has_autosession", "project",
                                     "language", "effective_language"}
    assert hello["session"]["project"] is None


async def test_the_hello_carries_the_documents_of_a_project_opened_with_no_client(domain,
                                                                                  tmp_path):
    """Startup with a `.retina` as argument: nobody was there to receive
    `restore_documents`, so the first client must find them in its hello."""
    from aiohttp.test_utils import TestClient, TestServer
    from rpcsession import Session

    blob = {"version": 1, "filesRoot": "/data"}
    path = str(tmp_path / "p.retina")
    domain.save_project(path, documents=blob)
    domain.close_project()
    domain.open_project(path)

    server = ServerApp(domain, port=0)
    server.attach()
    try:
        async with (TestClient(TestServer(server.aio)) as client,
                    client.ws_connect(f"/ws?t={server.token}") as ws):
            rpc = Session(ws)
            try:
                hello = await rpc.call("hello")
            finally:
                await rpc.close()
    finally:
        server.detach()

    assert hello["session"]["documents"] == blob
    assert hello["session"]["project"] == path


async def test_the_current_project_is_in_the_snapshot(session, domain, tmp_path):
    path = str(tmp_path / "p.retina")
    assert (await session.call("state.snapshot"))["project"] is None

    domain.save_project(path)

    assert (await session.call("state.snapshot"))["project"] == path


async def test_the_recents_are_readable_and_notified(session, domain, tmp_path):
    path = str(tmp_path / "p.retina")
    domain.save_project(path)

    state = await session.call("project.recent")

    assert state["recent_projects"] == [path]
    await _wait(session, "session.changed")


async def test_automatic_reopening_is_set_through_rpc(session, domain):
    await session.call("project.set_reopen", enabled=True)

    assert domain.session.reopen_enabled() is True
    assert (await session.call("project.recent"))["reopen"] is True


# --- interface language -------------------------------------------------------------------

async def test_the_language_is_set_through_rpc_and_returns_the_updated_state(session, domain,
                                                                             monkeypatch):
    """The reply carries the **effective** language: without it, the client would have to ask
    for the state again to know whether it should reload."""
    from retina import i18n

    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    i18n.invalidate()

    state = await session.call("project.set_language", language="fr")

    assert state["language"] == state["effective_language"] == "fr"
    assert domain.session.language() == "fr"
    await _wait(session, "session.changed")


async def test_going_back_to_automatic_clears_the_choice(session, domain, monkeypatch):
    from retina import i18n

    monkeypatch.setenv(i18n.ENV_VAR, "en")
    await session.call("project.set_language", language="fr")

    state = await session.call("project.set_language", language=None)

    assert state["language"] is None
    assert domain.session.language() is None


async def test_an_unknown_language_is_a_domain_error(session, domain):
    """And the previous choice stays in place — a refusal must break nothing."""
    with pytest.raises(RpcFailure, match="unknown language"):
        await session.call("project.set_language", language="klingon")

    assert domain.session.language() is None


async def test_closing_the_project_empties_the_windows(session, domain, tmp_path):
    domain.save_project(str(tmp_path / "p.retina"))

    await session.call("project.close")

    assert domain.windows == []
    assert (await session.call("state.snapshot"))["windows"] == []


# --- spontaneous deposit ------------------------------------------------------------------

async def test_a_spontaneous_deposit_keeps_the_blob_fresh_for_the_end_of_the_session(session,
                                                                                     domain):
    """This is what makes the automatic save on close useful: by then, no client is left to
    answer a request."""
    blob = {"version": 1, "scripts": {"docs": []}}

    await session.call("project.store_documents", documents=blob)

    assert domain.project_documents() == blob


async def test_a_spontaneous_deposit_is_not_echoed(session, domain):
    """The client deposits on every keystroke in an editor: echoing it would drown the console."""
    await session.call("project.store_documents", documents={"version": 1})
    await asyncio.sleep(0.1)

    echoes = [e["code"] for e in session.of("echo")]
    assert not any("store_documents" in code or "set_project_documents" in code
                   for code in echoes)


# --- restoration order ----------------------------------------------------------------------

async def test_the_views_are_restored_before_a_masked_recipe_becomes_replayable(
        session, domain, tmp_path):
    """Per-step masks designate views **by identifier**, resolved at execution time.
    A masked recipe launched right after opening must find its view."""
    import numpy as np
    from retina.model.image import Image

    domain.new_window(Image(np.full((16, 24, 3), 0.5, np.float32)), window_id="Mask01")
    path = str(tmp_path / "p.retina")
    domain.save_project(path)
    domain.close_project()

    await session.call("project.open", path=path)
    await _wait_job(session)
    session.clear()
    result = await session.call(
        "process.run_container",
        view="Test01",
        processes=[{"process_id": "Invert", "values": {},
                    "mask": "Mask01", "mask_inverted": False}],
    )
    finished = await _wait_job(session)

    assert result["job"].startswith("j")
    assert finished["method"] == "job.done", finished


async def test_the_blob_does_not_travel_in_the_hello_with_no_project_open(session, domain):
    """The client deposits its blob during the session, so the closing save finds it fresh.
    Without a guard, a browser connecting afterwards would be handed the tabs of a session it
    does not belong to."""
    await session.call("project.store_documents", documents={"version": 1, "filesRoot": "/x"})

    hello = await session.call("hello")

    assert domain.project_documents() == {"version": 1, "filesRoot": "/x"}
    assert "documents" not in hello["session"]
