"""The web console: same process, same ``app``, same echo.

This is the test of the console-completeness pillar: what you type here must act on the real
objects, not on a serialised copy, and produce exactly the same effects as a click in the
interface.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from retina.model.image import Image


async def test_the_shell_shares_the_app_object(session, domain):
    """``app`` in the console IS the served instance — not a proxy, not a global singleton."""
    result = await session.call("console.execute", code="app.set_zoom(3.0)")
    assert result["status"] == "ok"
    assert domain.active_window.viewport.zoom == 3.0


async def test_execution_produces_the_python_echo(session):
    """A script goes through the same methods as the interface, hence the same echo."""
    await session.call("hello")
    await session.call("console.execute", code="app.zoom_in()")
    await session.drain()
    assert "app.zoom_in()" in [p["code"] for p in session.of("echo")]


async def test_standard_output_is_broadcast(session):
    await session.call("hello")
    await session.call("console.execute", code="print('hello', 42)")
    await session.drain()
    assert session.text_of("console.stream") == "hello 42\n"


async def test_output_arrives_during_execution_not_after(session):
    """A long script must give news along the way, not all at the end.

    That is what the dedicated thread guarantees: if execution ran on the asyncio loop,
    nothing would go out before it finished.
    """
    await session.call("hello")
    task = asyncio.ensure_future(
        session.call(
            "console.execute",
            code="import time\nfor i in range(4):\n    print(i, flush=True)\n    time.sleep(0.2)",
        )
    )
    await asyncio.sleep(0.5)  # in the middle of the loop

    partial = session.text_of("console.stream")
    assert "0" in partial, "no output received during execution"
    assert not task.done(), "the script should still be running"

    await task
    assert "3" in session.text_of("console.stream")


async def test_the_result_of_an_expression_is_returned(session):
    result = await session.call("console.execute", code="2 + 40")
    assert result["status"] == "ok"
    assert result["repr"] == "42"


async def test_an_error_is_reported_without_killing_the_session(session):
    result = await session.call("console.execute", code="1 / 0")
    assert result["status"] == "error"
    assert "ZeroDivisionError" in result["error"]

    # the session stays usable
    assert (await session.call("console.execute", code="'still alive'"))["status"] == "ok"


async def test_the_full_traceback_is_broadcast(session):
    """IPython prints its tracebacks on **stdout** (``_showtraceback`` does a ``print``),
    not on stderr as one might expect. The client must therefore recognise a traceback by its
    content, not by its channel."""
    await session.call("hello")
    await session.call("console.execute", code="raise ValueError('boom')")
    await session.drain()

    output = session.text_of("console.stream")
    assert "Traceback" in output
    assert "ValueError" in output
    assert "boom" in output


async def test_state_persists_across_cells(session):
    await session.call("console.execute", code="my_variable = 7")
    assert (await session.call("console.execute", code="my_variable * 6"))["repr"] == "42"


async def test_the_execution_counter_advances(session):
    first = await session.call("console.execute", code="1")
    second = await session.call("console.execute", code="2")
    assert second["execution_count"] == first["execution_count"] + 1


async def test_the_result_is_not_also_printed_on_the_output(session):
    """The result of an expression must appear only **once**.

    IPython writes ``Out[1]: 42`` on stdout itself. That stream being captured and rendered as
    standard output, the transcript showed the same value twice: as raw text, then inside the
    typed block the client builds from ``repr``. Hence the muted displayhook.
    """
    await session.call("hello")
    result = await session.call("console.execute", code="6 * 7")
    await session.drain()

    assert result["repr"] == "42"
    assert "Out[" not in session.text_of("console.stream")


async def test_the_returned_number_is_the_one_of_the_executed_cell(session):
    """``execution_count`` is the cell's own, not the next one's.

    It was read after ``run_cell``, hence already incremented: the transcript announced
    ``Out[2]`` for the first cell. IPython's ``_1``, ``_2``... variables, meanwhile, carry the
    right number — the two contradicted each other.
    """
    first = await session.call("console.execute", code="111")
    # `_N` is populated by the displayhook: it is the reference, and it must designate what
    # we have just returned.
    echo = await session.call("console.execute", code=f"_{first['execution_count']}")
    assert echo["repr"] == "111"


# --- completion and introspection -------------------------------------------
async def test_completion_on_the_app_api(session):
    result = await session.call("console.complete", code="app.zoom_", cursor_pos=9)
    assert any(m.endswith("zoom_in") for m in result["matches"]), result["matches"]
    assert result["replace_end"] == 9


async def test_completion_reports_the_range_to_replace(session):
    code = "x = app.und"
    result = await session.call("console.complete", code=code, cursor_pos=len(code))
    replaced = code[result["replace_start"] : result["replace_end"]]
    assert replaced.endswith("und"), replaced


async def test_inspection_of_a_domain_method(session):
    result = await session.call("console.inspect", code="app.compute_auto_stf", cursor_pos=20)
    assert result["found"] is True
    assert "auto" in result["text"].lower()


async def test_inspection_of_an_unknown_name_does_not_raise(session):
    result = await session.call("console.inspect", code="really_does_not_exist", cursor_pos=21)
    assert result["found"] is False


async def test_inspection_returns_the_call_line(session):
    """Signature help needs the call line on its own, which the text block does not give.

    Hover makes do with `text` — that is already a readable block. But underlining the current
    parameter means slicing the signature apart, hence receiving it alone.
    """
    code = "app.open"
    result = await session.call("console.inspect", code=code, cursor_pos=len(code))
    assert result["found"] is True
    assert result["definition"].startswith("app.open(")
    assert "path" in result["definition"]


async def test_inspection_of_a_class_returns_init_definition(session):
    """A class files its call signature under `init_definition`, never under `definition`."""
    await session.call(
        "console.execute", code="class Target:\n    def __init__(self, x, y=1): pass"
    )
    result = await session.call("console.inspect", code="Target", cursor_pos=6)
    assert result.get("definition") is None
    assert result["init_definition"].startswith("Target(")


async def test_inspection_hides_the_docstring_sentinel(session):
    """IPython writes `<no docstring>` rather than an absence — relaying it would show a
    help bubble whose entire content is "no doc"."""
    await session.call("console.execute", code="def undocumented(a): pass")
    result = await session.call("console.inspect", code="undocumented", cursor_pos=12)
    assert "docstring" not in result


# --- errors --------------------------------------------------------------------
async def test_the_traceback_goes_out_on_stderr(session):
    """IPython prints its tracebacks on **stdout** (`_showtraceback` does a `print`).

    In a terminal this goes unnoticed; in our transcript, where colour comes from the stream
    name, an error looked exactly like an ordinary `print()` — a failing script seemed to have
    succeeded. Hence the redirection installed by `Console._ensure_shell`.
    """
    await session.call("console.execute", code="1 / 0")
    await session.drain()

    assert "ZeroDivisionError" in session.text_of("console.stream")
    streams = {p["name"] for p in session.of("console.stream") if p.get("text", "").strip()}
    assert streams == {"stderr"}


async def test_the_traceback_names_the_offending_line(session):
    """`Cell In[n], line k` is what the editor parses to mark the line."""
    session.clear()
    await session.call("console.execute", code="a = 1\nb = 2\nc = a / 0\n")
    await session.drain()
    assert "line 3" in session.text_of("console.stream")


async def test_a_syntax_error_is_reported_too(session):
    """It is raised *before* execution: the case that is missed most easily."""
    session.clear()
    result = await session.call("console.execute", code="def f(:")
    assert result["status"] == "error"
    assert "SyntaxError" in (result["error"] or "")
    await session.drain()
    assert "SyntaxError" in session.text_of("console.stream")


# --- interruption ------------------------------------------------------------
async def test_interrupting_an_infinite_loop(session):
    """Ctrl+C must hand back control — same mechanism and limits as a terminal IPython.

    Incidentally, this test also checks that the server handles messages from a single
    connection **in parallel**: if `console.execute` monopolised the read loop, the
    `console.interrupt` would never be read and the script would run forever.
    """
    await session.call("hello")
    task = asyncio.ensure_future(session.call("console.execute", code="while True:\n    pass"))
    await asyncio.sleep(0.4)  # let the loop get going

    assert await session.call("console.interrupt") is True
    result = await asyncio.wait_for(task, timeout=10)
    assert result["status"] in ("interrupted", "error")


async def test_the_viewport_stays_drivable_during_a_script(session, domain):
    """A long process must not freeze the interface — the promise of the dedicated thread."""
    await session.call("hello")
    task = asyncio.ensure_future(
        session.call("console.execute", code="import time; time.sleep(1.5)")
    )
    await asyncio.sleep(0.3)

    await session.call("app.set_zoom", zoom=5.0)  # must answer while the script runs
    assert domain.active_window.viewport.zoom == 5.0
    assert not task.done()
    await task


async def test_interrupting_with_nothing_running_returns_false(session):
    assert await session.call("console.interrupt") is False


# --- history -----------------------------------------------------------------
async def test_the_history_keeps_the_entries(session):
    await session.call("console.execute", code="history_marker = 1")
    history = await session.call("console.history", limit=20)
    assert any("history_marker" in entry for entry in history)


# --- side effects of a script ------------------------------------------------
async def test_a_script_that_opens_a_window_triggers_a_snapshot(session, domain):
    """There is no guessing what a script touched: we rebroadcast the whole state."""
    await session.call("hello")
    await session.drain()
    session.clear()

    await session.call(
        "console.execute",
        code=(
            "import numpy as np\n"
            "from retina.model.image import Image\n"
            "app.new_window(Image(np.zeros((4, 4, 1), dtype=np.float32)), window_id='FromScript')"
        ),
    )
    await session.drain()

    snapshots = session.of("state.changed")
    assert snapshots
    assert "FromScript" in [w["id"] for w in snapshots[-1]["windows"]]


async def test_a_process_applied_by_a_script_changes_the_generation(session, domain):
    domain.new_window(Image(np.linspace(0, 1, 64, dtype=np.float32).reshape(8, 8, 1)), "Target")
    snapshot = await session.call("state.snapshot")
    before = next(w for w in snapshot["windows"] if w["id"] == "Target")["views"][0]["pixel_gen"]

    await session.call(
        "console.execute",
        code=(
            "from retina.processes.channels import Invert\n"
            "Invert().execute_on(app.view('Target'))"
        ),
    )
    snapshot = await session.call("state.snapshot")
    after = next(w for w in snapshot["windows"] if w["id"] == "Target")["views"][0]["pixel_gen"]
    assert after == before + 1


@pytest.mark.parametrize("code", ["", "   ", "\n"])
async def test_an_empty_cell_breaks_nothing(session, code):
    assert (await session.call("console.execute", code=code))["status"] == "ok"


def test_the_shell_is_consistent_with_get_ipython(domain):
    """Regression: ``__IPYTHON__`` and ``get_ipython()`` must say the same thing.

    Creating a shell installs ``__IPYTHON__`` in the builtins, and several libraries use it as
    a flag *before* calling ``get_ipython()`` — astropy does so in its ``logger.py``. Building
    the shell without registering it as the instance made the two signals contradict each
    other: astropy believed it was running under IPython, got ``None``, and crashed on import.
    Observed effect: 46 completely unrelated tests failed, but only when the console tests ran
    before them.
    """
    import builtins

    from IPython import get_ipython
    from retina.server.console import Console

    console = Console(domain, lambda _name, _text: None)
    console._ensure_shell()

    assert getattr(builtins, "__IPYTHON__", False) is True
    assert get_ipython() is not None, "__IPYTHON__ set but get_ipython() empty"


def test_the_namespace_points_at_the_servers_app(domain):
    """The shell being a process-wide resource, each Console must reinject ITS app."""
    from retina.server.console import Console

    console = Console(domain, lambda _name, _text: None)
    shell = console._ensure_shell()
    assert shell.user_ns["app"] is domain
