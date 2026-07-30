"""Console/GUI parity of the preprocessing pipeline.

The project's golden rule: the GUI has no power of its own. A preprocessing run started from
the wizard must be **exactly** the one you get by typing three lines at the console — same
files, same pixels. This test runs it both ways and compares.
"""

from __future__ import annotations

import asyncio
import os

import numpy as np
import pytest

pytest.importorskip("astropy")


@pytest.fixture
def raws(tmp_path):
    from retina.pipeline.synthetic import make_dataset

    root = tmp_path / "raws"
    root.mkdir()
    make_dataset(str(root), "mono", filters=("L",))
    return str(root)


async def _wait(session, timeout: float = 60.0) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await session.drain(0.1)
        for method in ("job.done", "job.error", "job.cancelled"):
            if session.of(method):
                return {"method": method, **session.of(method)[-1]}
    raise AssertionError("the pipeline job never finished")


async def test_the_wizard_and_the_console_produce_the_same_thing(session, raws, tmp_path):
    from retina.io.fits import load_fits

    # --- over the wire, as the wizard would do it ---
    inventory = await session.call("pipeline.scan", path=raws)
    plan_gui = await session.call("pipeline.plan", inventory=inventory, preset="auto",
                                  output_dir=str(tmp_path / "gui"))
    await session.call("pipeline.run", plan=plan_gui)
    outcome = await _wait(session)
    assert outcome["method"] == "job.done"

    # --- at the console, without touching the shell ---
    import retina

    inv = retina.pipeline.scan(raws)
    plan_console = retina.pipeline.plan(inv, preset="auto",
                                        output_dir=str(tmp_path / "console"))
    report = retina.pipeline.run(plan_console)

    # same steps, same output names
    assert [s["id"] for s in plan_gui["steps"]] == [s.id for s in plan_console.steps]
    assert sorted(os.path.basename(p) for p in outcome["result"]["results"]) == sorted(
        os.path.basename(p) for p in report.results)

    # same pixels
    for a, b in zip(sorted(outcome["result"]["results"]), sorted(report.results), strict=True):
        assert np.allclose(load_fits(a)[0].data, load_fits(b)[0].data, atol=1e-6), \
            os.path.basename(a)


async def test_the_wizard_echoes_the_script_that_reproduces_it(session, raws, tmp_path):
    """The echo must be runnable as is: it is the source of recipes."""
    await session.call("pipeline.scan", path=raws)
    inventory = await session.call("pipeline.scan", path=raws)
    session.clear()
    plan = await session.call("pipeline.plan", inventory=inventory,
                              output_dir=str(tmp_path / "out"))
    await session.call("pipeline.run", plan=plan)
    await _wait(session)

    codes = [p["code"] for p in session.of("echo")]
    script = "\n".join(codes)

    assert "retina.pipeline.plan(" in script
    assert "retina.pipeline.run(plan)" in script
    compile(script, "<echo>", "exec")


async def test_no_pipeline_method_bypasses_the_domain(session):
    """Every RPC must have its counterpart in `retina.pipeline` / `app.pipeline`."""
    import retina

    methods = await session.call("rpc.methods")
    names = [m.split(".", 1)[1] for m in methods if m.startswith("pipeline.")]

    for name in names:
        if name == "report":  # a retrieval convenience, not a domain action
            continue
        assert hasattr(retina.app.pipeline, name), f"app.pipeline.{name} missing"


async def test_the_domain_does_not_depend_on_the_shell():
    """`import retina.pipeline` must work without aiohttp — headless first."""
    import subprocess
    import sys

    code = ("import retina.pipeline, sys; "
            "assert 'aiohttp' not in sys.modules; "
            "assert 'retina.server' not in sys.modules")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
