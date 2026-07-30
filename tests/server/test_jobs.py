"""Process execution: jobs, progress, cancellation, effects on the state.

The contract: ``process.run``
returns immediately, the result arrives through notifications, and the snapshot follows —
because a process may have changed the pixels, the history, or opened a window.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from retina.model.image import Image
from retina.process.base import Process
from rpcsession import RpcFailure


async def _wait_job(session, timeout: float = 10.0) -> dict:
    """Waits for the running job to finish and returns its terminal notification."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        for method in ("job.done", "job.error", "job.cancelled"):
            events = session.of(method)
            if events:
                return {"method": method, **events[-1]}
        await asyncio.sleep(0.05)
    raise AssertionError(f"no job ever finished within {timeout}s: {session.notifications}")


# --- catalog -----------------------------------------------------------------
async def test_the_catalog_exposes_the_parameter_schema(session):
    """The frontend generates its forms from this schema: it must be complete."""
    catalog = await session.call("process.list")
    assert len(catalog) > 100

    gaussian = next(p for p in catalog if p["process_id"] == "GaussianConvolution")
    sigma = next(p for p in gaussian["parameters"] if p["id"] == "sigma")
    assert sigma["type"] == "real"
    assert sigma["default"] == 2.0
    assert sigma["min"] == 0.0 and sigma["max"] == 50.0
    assert gaussian["is_maskable"] is True
    assert gaussian["supports_realtime"] is True
    assert gaussian["has_doc"] is True


async def test_the_whole_catalog_is_serializable(session):
    """A single non-serializable default would break the loading of the entire catalog."""
    catalog = await session.call("process.list")
    types = {p["type"] for process in catalog for p in process["parameters"]}
    assert {"real", "int", "str", "enum", "bool", "path", "points"} <= types


async def test_the_schema_injects_dynamic_choices(session, monkeypatch):
    """``parameter_choices`` fills in a dropdown that the descriptor leaves empty.

    The AI model selector is the real case: ``model_id`` is an ``enum`` with no static
    choices, filled on the fly from the live catalog. We force that catalog so as to depend
    neither on the network nor on a GraXpert install.
    """
    from retina.ai import models

    monkeypatch.setattr(models, "choices_for_tasks",
                        lambda tasks: ("latest", "graxpert-denoise-9.9.9"))

    catalog = await session.call("process.list")
    denoise = next(p for p in catalog if p["process_id"] == "AIDenoise")
    model_id = next(p for p in denoise["parameters"] if p["id"] == "model_id")
    assert model_id["choices"] == ["latest", "graxpert-denoise-9.9.9"]

    # process.get (a single schema) goes through the same path: same choices.
    single = await session.call("process.get", process_id="AIDenoise")
    single_model = next(p for p in single["parameters"] if p["id"] == "model_id")
    assert single_model["choices"] == ["latest", "graxpert-denoise-9.9.9"]


async def test_the_schema_carries_conditional_visibility(session):
    """``visible_when`` travels all the way to the client, which hides out-of-backend fields.

    A field with no clause stays ``None`` (always visible); those of ``BackgroundExtraction``
    say which backend makes them appear.
    """
    single = await session.call("process.get", process_id="BackgroundExtraction")
    by_id = {p["id"]: p for p in single["parameters"]}

    assert by_id["backend"]["visible_when"] is None             # the controller, always there
    assert by_id["subtract"]["visible_when"] is None
    assert by_id["box_size"]["visible_when"] == {"param": "backend", "values": ["photutils"]}
    assert by_id["model_id"]["visible_when"] == {"param": "backend", "values": ["ai"]}


# --- execution ---------------------------------------------------------------
async def test_applying_a_process_changes_the_pixels(session, domain):
    await session.call("hello")
    before = domain.active_view.image.data.copy()

    result = await session.call("process.run", process_id="Invert", params={})
    assert result["job"].startswith("j")
    await _wait_job(session)

    assert not np.allclose(domain.active_view.image.data, before)


async def test_run_returns_immediately(session, domain):
    """The job leaves for the background: the RPC reply must not wait for the result."""
    await session.call("hello")
    loop = asyncio.get_running_loop()
    start = loop.time()
    await session.call("process.run", process_id="GaussianConvolution", params={"sigma": 2.0})
    assert loop.time() - start < 1.0
    await _wait_job(session)


async def test_the_process_pushes_a_history_entry(session, domain):
    await session.call("hello")
    await session.call("process.run", process_id="Invert", params={})
    await _wait_job(session)

    snapshot = await session.call("state.snapshot")
    history = snapshot["windows"][0]["views"][0]["history"]
    assert history["labels"] == ["initial", "Invert"]
    assert history["can_undo"] is True


async def test_the_end_of_the_job_triggers_a_snapshot(session):
    """A process may have changed everything: we rebroadcast the full state rather than guess."""
    await session.call("hello")
    await session.drain()
    session.clear()

    await session.call("process.run", process_id="Invert", params={})
    await _wait_job(session)
    await session.drain()

    assert session.of("state.changed"), "no snapshot after the job finished"


async def test_the_pixel_generation_changes(session, domain):
    await session.call("hello")
    before = (await session.call("state.snapshot"))["windows"][0]["views"][0]["pixel_gen"]
    await session.call("process.run", process_id="Invert", params={})
    await _wait_job(session)
    after = (await session.call("state.snapshot"))["windows"][0]["views"][0]["pixel_gen"]
    assert after == before + 1


async def test_execution_produces_the_python_echo(session):
    """A process launched from the interface must write its console equivalent."""
    await session.call("hello")
    await session.call("process.run", process_id="GaussianConvolution", params={"sigma": 1.5})
    await _wait_job(session)
    await session.drain()

    echoes = [p["code"] for p in session.of("echo")]
    assert any("GaussianConvolution(sigma=1.5)" in code for code in echoes), echoes


async def test_targeting_a_preview_explicitly(session, domain):
    """``view`` designates the target: a preview is processed just like a main view."""
    await session.call("hello")
    domain.new_preview(1, 1, 12, 10, "core")
    await session.call("process.run", process_id="Invert", params={}, view="core")
    await _wait_job(session)

    snapshot = await session.call("state.snapshot")
    views = {v["id"]: v for v in snapshot["windows"][0]["views"]}
    assert views["core"]["history"]["labels"] == ["initial", "Invert"]
    # the main view has not moved
    assert views["Test01"]["history"]["labels"] == ["initial"]


# --- errors ------------------------------------------------------------------
async def test_an_invalid_parameter_is_rejected_before_launching(session):
    with pytest.raises(RpcFailure) as excinfo:
        await session.call("process.run", process_id="Invert", params={"does_not_exist": 1})
    assert excinfo.value.code == -32000


async def test_an_unknown_process_is_rejected(session):
    with pytest.raises(RpcFailure):
        await session.call("process.run", process_id="DoesNotExist")


async def test_a_process_failure_comes_back_as_job_error(session, domain):
    """A domain exception must come back to the client, not die inside a thread."""
    await session.call("hello")
    # PixelMath with an invalid expression: fails at execution, not at construction
    await session.call(
        "process.run", process_id="PixelMath",
        params={"expression": "this_variable_does_not_exist"}
    )
    event = await _wait_job(session)
    assert event["method"] == "job.error"
    assert event["message"]


async def test_without_an_active_view_the_refusal_is_immediate(session, domain):
    """Better an RPC error right away than a job that leaves only to fail."""
    domain.close_window(domain.active_window)
    with pytest.raises(RpcFailure) as excinfo:
        await session.call("process.run", process_id="Invert")
    assert "target view" in str(excinfo.value)


# --- cancellation ------------------------------------------------------------
def test_cancelling_a_job_still_queued(domain):
    """A job that has not started is removed for good, and reported as cancelled.

    Tested on the ``JobRunner`` directly, with a gate occupying the single worker: an earlier
    version saturated the pool with real convolutions and turned out to be flaky — on a 24×16
    image they finish before there is any time to cancel.

    In flight, cancellation stays cooperative and has no effect in the middle of an ``_apply``
    as long as processes do not call ``_checkpoint()`` — a known limit of the catalog,
    documented in ``server/jobs.py``.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from retina.processes.channels import Invert
    from retina.server.jobs import JobRunner

    events: list[tuple[str, dict]] = []
    gate = threading.Event()

    with ThreadPoolExecutor(max_workers=1) as executor:
        runner = JobRunner(
            domain, executor, lambda m, p: events.append((m, p)), lambda: None
        )
        executor.submit(gate.wait)  # the single worker is blocked: nothing else can start
        try:
            job_id = runner.submit(Invert(), "Invert", None)
            assert runner.cancel(job_id) is True
            assert runner.get(job_id).state == "cancelled"
            assert any(method == "job.cancelled" for method, _ in events)
            # a finished job does not get cancelled twice
            assert runner.cancel(job_id) is False
        finally:
            gate.set()


async def test_cancelling_an_unknown_job_returns_false(session):
    assert await session.call("process.cancel", job="never-seen") is False


# --- tracking ----------------------------------------------------------------
async def test_jobs_in_flight_appear_in_the_snapshot(session, domain):
    await session.call("hello")
    domain.new_window(Image(np.zeros((256, 256, 3), dtype=np.float32)), window_id="Large")
    await session.call("process.run", process_id="GaussianConvolution", params={"sigma": 8.0})

    # deliberate race: we look while it is running
    snapshot = await session.call("state.snapshot")
    jobs = snapshot["jobs"]
    if jobs:  # the job may already be over on a fast machine
        assert jobs[0]["process_id"] == "GaussianConvolution"
        assert jobs[0]["state"] in ("queued", "running")
    await _wait_job(session)
    assert (await session.call("process.jobs")) == []


async def test_a_global_process_creates_a_window(session, domain):
    """Global processes do not target a view: they produce a new window."""
    await session.call("hello")
    catalog = await session.call("process.list")
    assert any(p["is_global"] for p in catalog), "no global process in the catalog"


# --- progress becomes real ----------------------------------------------------------

async def test_an_instrumented_process_reports_a_fraction(session, tmp_path):
    """The bar goes from "it is running" to "here is where we are" — that was the whole point."""
    import numpy as np
    from retina.io.fits import save_fits
    from retina.model.image import Image

    paths = []
    for i in range(4):
        p = str(tmp_path / f"f{i}.fits")
        save_fits(p, Image(np.full((8, 8, 1), 0.3, dtype=np.float32)))
        paths.append(p)

    await session.call("process.run", process_id="Integration",
                       params={"frames": paths, "rejection": "none"})
    await _wait_job(session)

    fractions = [p["fraction"] for p in session.of("job.progress")
                 if p["fraction"] is not None]
    assert fractions, "no fraction reported"
    assert fractions == sorted(fractions)
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert any("Reading" in p["message"] for p in session.of("job.progress"))


def test_the_job_remembers_its_progress(domain):
    """Without memorization, reconnecting mid-run would lose the bar."""
    from concurrent.futures import ThreadPoolExecutor

    from retina.server.jobs import JobRunner

    events: list[tuple[str, dict]] = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        runner = JobRunner(domain, executor, lambda m, p: events.append((m, p)),
                           lambda: None)
        job_id = runner.submit(_ReportingProcess(), "Reporter", None)
        runner.get(job_id).future.result(timeout=10)

    job = runner.get(job_id)
    assert job.state == "done"
    assert job.fraction == 1.0
    # and the snapshot publishes it, since it goes through to_dict()
    assert "fraction" in job.to_dict()
    assert "progress_message" in job.to_dict()


def test_the_snapshot_publishes_the_progress(domain):
    """A job in flight must say where it stands, not merely that it exists."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from retina.server.jobs import JobRunner

    barrier = threading.Event()
    seen: list[dict] = []

    class _Blocking(_ReportingProcess):
        def _apply(self, data):
            self._progress(0.5, "halfway")
            seen.append({})
            barrier.wait(timeout=5)
            return data

    with ThreadPoolExecutor(max_workers=1) as executor:
        runner = JobRunner(domain, executor, lambda m, p: None, lambda: None)
        job_id = runner.submit(_Blocking(), "Blocking", domain.active_view.id)
        for _ in range(200):  # let the worker reach the report
            if seen:
                break
            threading.Event().wait(0.01)

        active = runner.active()
        assert [j["id"] for j in active] == [job_id]
        assert active[0]["fraction"] == 0.5
        assert active[0]["progress_message"] == "halfway"

        barrier.set()
        runner.get(job_id).future.result(timeout=10)


class _ReportingProcess(Process):
    """Test process: reports three times, then returns the image unchanged."""

    process_id = "Reporter"

    def _apply(self, data):
        for i in range(3):
            self._progress((i + 1) / 3, f"step {i + 1}/3")
        return data


async def test_the_result_of_a_measurement_process_reaches_the_client(session, domain):
    """An inspection process has only its `result` to hand back — and it never arrived.

    `JobRunner._run` only picked `job.result` up on the `call` path (the pipeline's one). A
    `DynamicPSF` launched from its form therefore measured perfectly, and the client saw nothing
    of it: no table, no ellipse. The fix is generic, so `Statistics` and
    `RadialProfileMeasurement` benefit from it too.
    """
    import numpy as np
    from retina.model.image import Image

    rng = np.random.default_rng(3)
    field = (rng.random((60, 60)) * 0.002).astype(np.float32)
    ys, xs = np.mgrid[0:60, 0:60]
    for (cx, cy) in [(20, 20), (40, 35)]:
        field += (0.8 * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 1.6**2)))).astype(
            np.float32
        )
    domain.new_window(Image(np.clip(field, 0, 1)[:, :, None]), window_id="Stars")

    await session.call("hello")
    await session.call("process.run", process_id="DynamicPSF", params={}, view="Stars")

    finished = await _wait_job(session)
    assert finished["method"] == "job.done"
    assert finished["result"] is not None, "the measurement result must travel with job.done"
    assert finished["result"]["n_stars"] >= 1
    assert finished["result"]["stars"], "the per-star detail must be present"
