"""MCP server: handshake, tools, resources, prompts.

The contract these tests hold: an agent that speaks MCP can inspect the session, see an
image, apply a process and undo it -- **sharing the user's live state**, not a copy. And the
surface it discovers stays small enough to fit in a context: that is what the size guard is
for.
"""

from __future__ import annotations

import base64
import io
import json

import pytest
from retina.app import Application
from retina.server.core import ServerApp

pytest.importorskip("aiohttp", reason="the [web] extra is not installed")

from aiohttp.test_utils import TestClient, TestServer
from conftest import gradient


@pytest.fixture
def mcp_server(domain: Application) -> ServerApp:
    return ServerApp(domain, port=0, mcp=True)


@pytest.fixture
async def mcp(mcp_server: ServerApp):
    """MCP client: speaks JSON-RPC to ``/mcp`` with the session token."""
    mcp_server.attach()
    async with TestClient(TestServer(mcp_server.aio)) as client:
        yield _McpClient(client, mcp_server)
    mcp_server.detach()


class _McpClient:
    def __init__(self, client: TestClient, server: ServerApp) -> None:
        self._client = client
        self.server = server
        self._id = 0

    async def send(self, method: str, params: dict | None = None, expect_error: bool = False):
        self._id += 1
        response = await self._client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}},
            headers={"X-Retina-Token": self.server.token},
        )
        assert response.status == 200, await response.text()
        payload = await response.json()
        if expect_error:
            return payload["error"]
        assert "error" not in payload, payload["error"]
        return payload["result"]

    async def call(self, tool: str, **arguments):
        """Call a tool and return its decoded JSON payload."""
        result = await self.send("tools/call", {"name": tool, "arguments": arguments})
        assert result["isError"] is False, result["content"]
        return json.loads(result["content"][0]["text"])

    async def call_raw(self, tool: str, **arguments) -> dict:
        return await self.send("tools/call", {"name": tool, "arguments": arguments})


# --- handshake ----------------------------------------------------------------
async def test_initialize_announces_the_capabilities(mcp):
    result = await mcp.send("initialize", {"protocolVersion": "2025-06-18"})
    assert result["serverInfo"]["name"] == "retina"
    assert set(result["capabilities"]) == {"tools", "resources", "prompts"}
    # The welcome instructions state the one thing an agent cannot guess: a linear
    # astronomical image is black until you stretch it.
    assert "stretch" in result["instructions"]


async def test_the_session_is_assigned_on_initialize(mcp):
    response = await mcp._client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"X-Retina-Token": mcp.server.token},
    )
    assert response.headers.get("Mcp-Session-Id")


async def test_a_notification_gets_no_response(mcp):
    response = await mcp._client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"X-Retina-Token": mcp.server.token},
    )
    assert response.status == 202
    assert await response.text() == ""


async def test_without_a_token_the_endpoint_refuses(mcp):
    response = await mcp._client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status == 401


async def test_mcp_is_absent_by_default(client):
    """Without ``mcp=True`` the route does not exist: enabling an agent is a deliberate act."""
    response = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"X-Retina-Token": client.retina.token},
    )
    assert response.status == 404


# --- tool catalogue -----------------------------------------------------------
async def test_the_tools_have_a_valid_schema(mcp):
    tools = (await mcp.send("tools/list"))["tools"]
    names = {t["name"] for t in tools}
    assert {"get_state", "render_view", "apply_process", "pipeline", "execute_python"} <= names
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        assert tool["description"].strip()


async def test_the_surface_stays_compact(mcp):
    """Anti-bloat guard: ``tools/list`` goes out in *every* conversation.

    This is not aesthetics -- every thousand characters here is paid for by the agent on
    every turn. If this bound breaks, it is the sign that one tool too many was added, or
    that a description has turned into a manual.
    """
    tools = (await mcp.send("tools/list"))["tools"]
    assert len(tools) <= 20
    size = len(json.dumps(tools))
    # 18 tools weigh ~12k characters; the bound sits at 14k to let one more tool breathe
    # without revising the test at every addition -- but a doubling would signal a
    # description turned manual, or ten tools too many.
    assert size < 14_000, f"tool catalogue too large: {size} characters"


# --- state and reading --------------------------------------------------------
async def test_get_state_describes_the_session(mcp, domain):
    state = await mcp.call("get_state")
    assert state["active_view"] == domain.active_view.id
    window = state["windows"][0]
    assert window["window"] == "Test01"
    assert window["views"][0]["size"] == [24, 16, 3]
    # Projection: neither viewport nor panel layout -- the agent has no use for them.
    assert "viewport" not in window
    assert "layout" not in state


async def test_list_processes_does_not_dump_the_schemas(mcp):
    catalog = await mcp.call("list_processes")
    assert catalog["count"] > 100
    entry = next(p for p in catalog["processes"] if p["process_id"] == "GaussianConvolution")
    assert "parameters" not in entry
    assert entry["summary"]


async def test_describe_process_returns_the_schema_and_the_doc(mcp):
    described = await mcp.call("describe_process", process_id="GaussianConvolution")
    sigma = next(p for p in described["parameters"] if p["id"] == "sigma")
    assert sigma["type"] == "real" and sigma["default"] == 2.0
    assert described["documentation"].strip()


async def test_an_unknown_process_is_a_tool_error(mcp):
    """The agent must *read* the failure to correct itself: an error result, not JSON-RPC."""
    result = await mcp.call_raw("describe_process", process_id="Nonexistent")
    assert result["isError"] is True
    assert "Nonexistent" in result["content"][0]["text"]


async def test_get_stats_returns_the_robust_statistics(mcp, domain):
    stats = await mcp.call("get_stats", bins=16)
    assert len(stats["channels"]) == 3
    assert stats["channels"][0]["median"] == pytest.approx(domain.active_view.image.median(0))
    assert len(stats["channels"][0]["counts"]) == 16


async def test_get_stats_probes_a_point(mcp):
    probe = await mcp.call("get_stats", x=12, y=8)
    assert probe["readout"] is not None


# --- action -------------------------------------------------------------------
async def test_apply_process_modifies_the_view_and_returns_the_echo(mcp, domain):
    before = domain.active_view.image.data.copy()
    outcome = await mcp.call("apply_process", process_id="Invert")

    assert outcome["state"] == "done"
    assert not (domain.active_view.image.data == before).all()
    # The history did receive the step -- that is what makes the gesture reversible.
    assert outcome["view"]["history"][-1].startswith("Invert")
    assert outcome["view"]["pixel_gen"] >= 1
    # The echo: the Python code the agent could have typed. That is what teaches it the API.
    assert any("Invert" in line for line in outcome["echo"])


async def test_history_undoes_the_process(mcp, domain):
    before = domain.active_view.image.data.copy()
    await mcp.call("apply_process", process_id="Invert")
    undone = await mcp.call("history", action="undo")

    assert undone["applied"] is True
    assert (domain.active_view.image.data == before).all()


async def test_apply_recipe_executes_in_order(mcp, domain):
    outcome = await mcp.call(
        "apply_recipe",
        processes=[
            {"process_id": "Invert", "values": {}},
            {"process_id": "GaussianConvolution", "values": {"sigma": 1.0}},
        ],
    )
    assert outcome["state"] == "done"
    # Order is the very meaning of a recipe -- stretch then denoise is not denoise then
    # stretch. Each step keeps its own history entry, so it stays separately undoable.
    assert domain.active_view.history_labels() == ["initial", "Invert", "GaussianConvolution"]


async def test_set_stf_auto_makes_the_image_visible(mcp, domain):
    stf = await mcp.call("set_stf", mode="auto")
    assert stf["stf"]["channels"]
    assert domain.active_window.main_view.stf is not None


async def test_previews_creates_a_subregion(mcp, domain):
    created = await mcp.call("previews", action="new", rect=[0, 0, 8, 8], preview_id="corner")
    assert created["preview"] == "corner"
    assert [p.id for p in domain.active_window.previews] == ["corner"]


async def test_open_images_opens_a_file(mcp, domain, tmp_path):
    from retina.io.fits import save_fits

    path = tmp_path / "target.fits"
    save_fits(str(path), gradient(12, 10, 1))

    opened = await mcp.call("open_images", paths=[str(path)])
    assert len(opened["windows"]) == 1
    assert len(domain.windows) == 2


# --- console ------------------------------------------------------------------
async def test_execute_python_shares_the_users_namespace(mcp, domain):
    """The agent's console **is** the user's: that is the whole point."""
    result = await mcp.call("execute_python", code="print(len(app.windows)); app.windows[0].id")
    assert result["status"] == "ok"
    assert result["repr"] == "'Test01'"
    # The captured stream is IPython's, `Out[n]:` included: the agent sees exactly what the
    # user would see in their console.
    assert result["stdout"].startswith("1\n")


async def test_parity_between_the_typed_tool_and_the_console(mcp, domain):
    """A gesture made through the typed tool and through the console must give the same state.

    This is the project's golden rule seen from the agent: the tool has no power of its own,
    it calls the same API as the one exposed to the console.
    """
    await mcp.call("apply_process", process_id="Invert")
    via_tool = domain.active_view.image.data.copy()
    await mcp.call("history", action="undo")

    await mcp.call("execute_python", code="app.apply(retina.Invert())")
    assert (domain.active_view.image.data == via_tool).all()


# --- rendering ----------------------------------------------------------------
async def test_render_view_returns_a_png_image(mcp):
    pytest.importorskip("PIL", reason="pillow is not installed")
    from PIL import Image as PilImage

    result = await mcp.call_raw("render_view", stretch="auto", max_size=64)
    assert result["isError"] is False
    blocks = result["content"]
    assert blocks[0]["type"] == "text"  # caption: real dimensions and stretch
    image = blocks[1]
    assert image["type"] == "image" and image["mimeType"] == "image/png"

    decoded = PilImage.open(io.BytesIO(base64.b64decode(image["data"])))
    assert max(decoded.size) <= 64
    # A flat rendering would signal a failed stretch -- the fixture's gradient must show.
    assert len(decoded.convert("L").getcolors(maxcolors=65536)) > 4


async def test_render_view_downsamples_large_images(mcp, domain):
    pytest.importorskip("PIL", reason="pillow is not installed")
    from PIL import Image as PilImage

    domain.new_window(gradient(600, 400, 1), window_id="Large")
    result = await mcp.call_raw("render_view", max_size=100)
    image = PilImage.open(io.BytesIO(base64.b64decode(result["content"][1]["data"])))
    assert max(image.size) <= 100


# --- resources and prompts ----------------------------------------------------
async def test_the_resources_expose_the_documentation(mcp):
    listed = await mcp.send("resources/list")
    assert listed["resources"][0]["uri"] == "retina://doc/index"

    read = await mcp.send("resources/read", {"uri": "retina://doc/HistogramTransformation"})
    assert read["contents"][0]["mimeType"] == "text/markdown"
    assert read["contents"][0]["text"].strip()


async def test_the_prompts_guide_both_journeys(mcp):
    prompts = {p["name"] for p in (await mcp.send("prompts/list"))["prompts"]}
    assert prompts == {"preprocess_raw_folder", "assess_image"}

    prompt = await mcp.send("prompts/get",
                            {"name": "preprocess_raw_folder", "arguments": {"path": "/data/M31"}})
    text = prompt["messages"][0]["content"]["text"]
    assert "/data/M31" in text
    # The exclude / do-not-stack distinction is the business trap of preprocessing: the
    # prompt must state it, or the agent will invalidate caches without knowing.
    assert "set_rejects" in text and "exclude" in text


# --- jobs ---------------------------------------------------------------------
async def test_a_long_process_can_be_tracked_without_waiting(mcp):
    launched = await mcp.call("apply_process", process_id="Invert", wait=False)
    assert launched["job"].startswith("j")
    finished = await mcp.call("jobs", action="wait", job=launched["job"])
    assert finished["state"] == "done"


# --- pipeline -----------------------------------------------------------------
@pytest.fixture
def raws(tmp_path):
    pytest.importorskip("astropy")
    from retina.pipeline.synthetic import make_dataset

    root = tmp_path / "raws"
    root.mkdir()
    make_dataset(str(root), "mono", filters=("L",))
    return str(root)


async def test_the_pipeline_goes_through_handles(mcp, raws):
    """An inventory of hundreds of frames must never cross the agent's context.

    The scan returns a handle and a summary; the following steps quote it. That is the only
    difference with the web shell, which receives the whole inventory because it displays it.
    """
    inventory = await mcp.call("pipeline", action="scan", path=raws)
    assert inventory["inventory"] == "inv1"
    assert inventory["frames"] == 13
    assert set(inventory["by_kind"]) == {"light", "dark", "flat", "bias"}
    # The summary, not the list of files.
    assert "frames" not in inventory.get("by_kind", {})

    survey = await mcp.call("pipeline", action="survey", inventory="inv1")
    lights = [g for g in survey["groups"] if g["kind"] == "light"]
    assert lights and lights[0]["calibration"]["flat"]

    plan = await mcp.call("pipeline", action="plan", inventory="inv1")
    assert plan["plan"] == "plan1"
    assert plan["steps"] > 0
    assert plan["outline"][0]["kind"]


async def test_an_unknown_handle_is_explained(mcp, raws):
    result = await mcp.call_raw("pipeline", action="plan", inventory="inv99")
    assert result["isError"] is True
    assert "inv99" in result["content"][0]["text"]


async def test_the_pipeline_goes_from_scan_to_integration(mcp, raws):
    await mcp.call("pipeline", action="scan", path=raws)
    await mcp.call("pipeline", action="plan", inventory="inv1")
    report = await mcp.call("pipeline", action="run", plan="plan1")

    assert report["state"] == "done", report.get("message")
    assert report["report"]["results"]


# --- stdio transport ----------------------------------------------------------
async def test_the_stdio_transport_serves_the_same_tools(mcp_server):
    """Same registry, different pipe: ``python -m retina.mcp`` for a client with no interface.

    We feed the loop with real text streams rather than a subprocess: what must be checked
    here is the line-by-line framing and the shared registry, not Python's ability to start.
    """
    import io

    from retina.server.mcp.stdio import serve

    entry = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": "get_state", "arguments": {}}}) + "\n"
    )
    output = io.StringIO()

    assert await serve(mcp_server, entry, output) == 0

    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [r["id"] for r in responses] == [1, 2, 3]
    assert responses[0]["result"]["serverInfo"]["name"] == "retina"
    assert len(responses[1]["result"]["tools"]) == len(mcp_server.mcp.mcp.registry)
    state = json.loads(responses[2]["result"]["content"][0]["text"])
    assert state["windows"][0]["window"] == "Test01"


# --- persistent token ---------------------------------------------------------
async def test_the_persistent_mcp_token_opens_only_mcp(domain, tmp_path, monkeypatch):
    """The second token is confined to ``/mcp`` -- and must not become a master key.

    It exists because an agent configuration file, written once, cannot carry the session
    token drawn at every launch. That convenience must not widen the surface: not the
    WebSocket, not the pixels, not the project documents.
    """
    monkeypatch.setattr("retina.paths.config_dir", lambda: tmp_path)
    from retina.server.security import mcp_token

    token = mcp_token()
    server = ServerApp(domain, port=0, mcp=True)
    server.attach()
    try:
        async with TestClient(TestServer(server.aio)) as client:
            allowed = await client.post(
                "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers={"X-Retina-Token": token},
            )
            assert allowed.status == 200

            for route in ("/ws", f"/api/pixels/{domain.active_view.id}.f16"):
                denied = await client.get(route, headers={"X-Retina-Token": token})
                assert denied.status == 401, route
    finally:
        server.detach()


async def test_the_mcp_client_does_not_receive_the_session_cookie(domain, tmp_path, monkeypatch):
    """Setting the session cookie would hand it the whole server -- exactly what confining
    the MCP token is meant to avoid."""
    monkeypatch.setattr("retina.paths.config_dir", lambda: tmp_path)
    from retina.server.security import mcp_token

    token = mcp_token()
    server = ServerApp(domain, port=0, mcp=True)
    server.attach()
    try:
        async with TestClient(TestServer(server.aio)) as client:
            response = await client.post(
                "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                headers={"X-Retina-Token": token},
            )
            assert "Set-Cookie" not in response.headers
    finally:
        server.detach()


async def test_the_persistent_token_survives_a_restart(tmp_path, monkeypatch):
    monkeypatch.setattr("retina.paths.config_dir", lambda: tmp_path)
    from retina.server.security import mcp_token

    assert mcp_token() == mcp_token()
    assert (tmp_path / "mcp-token").is_file()


# --- interface tools ----------------------------------------------------------
async def test_open_script_writes_and_notifies(mcp, tmp_path):
    """The assistant drops a script in front of the user: a file plus a tab."""
    notifications = []
    mcp.server.broadcast.notify = lambda m, p: notifications.append((m, p))

    path = str(tmp_path / "trial.py")
    result = await mcp.call("open_script", content="print('hello')", path=path)

    assert result["opened"] == path
    assert (tmp_path / "trial.py").read_text(encoding="utf-8") == "print('hello')"
    command = next(p for m, p in notifications if m == "scripts.command")
    assert command["op"] == "open" and command["path"] == path


async def test_open_script_without_a_path_opens_a_tab(mcp):
    notifications = []
    mcp.server.broadcast.notify = lambda m, p: notifications.append((m, p))

    result = await mcp.call("open_script", content="x = 1", title="draft")

    assert result["opened"] == "draft"
    command = next(p for m, p in notifications if m == "scripts.command")
    assert command["path"] is None and command["text"] == "x = 1"


async def test_open_documentation_opens_the_panel_and_targets_the_page(mcp):
    notifications = []
    mcp.server.broadcast.notify = lambda m, p: notifications.append((m, p))

    result = await mcp.call("open_documentation", process_id="HistogramTransformation")

    assert result["opened"] == "HistogramTransformation"
    # The panel opens through the domain (parity), the notification targets the page.
    assert mcp.server.app.layout.is_visible("doc")
    command = next(p for m, p in notifications if m == "docs.command")
    assert command["process_id"] == "HistogramTransformation"


async def test_open_documentation_rejects_an_unknown_process(mcp):
    result = await mcp.call_raw("open_documentation", process_id="Nonexistent")
    assert result["isError"] is True
