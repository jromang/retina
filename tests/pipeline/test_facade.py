"""``app.pipeline``: console/GUI parity for preprocessing.

Every gesture of the wizard must echo into the console the Python that would have produced
it. Strung end to end, those echoes form the executable script of the preprocessing one has
just done with the mouse — that is the source of recipes, and pillar #2 of the project.
"""

from __future__ import annotations

import pytest
from retina.app import Application
from retina.pipeline.presets import PRESETS


@pytest.fixture
def app_echo():
    """A brand new application whose echoes are captured."""
    app = Application()
    echoes: list[str] = []
    app.on_echo = echoes.append
    return app, echoes


def test_every_call_echoes_its_python_equivalent(app_echo, raws_mono, tmp_path):
    app, echoes = app_echo

    inventory = app.pipeline.scan(raws_mono)
    plan = app.pipeline.plan(inventory, "mono_lrgb", output_dir=str(tmp_path))
    app.pipeline.run(plan)

    assert echoes == [
        f"inventory = retina.pipeline.scan({raws_mono!r})",
        f"plan = retina.pipeline.plan(inventory, preset='mono_lrgb', "
        f"output_dir={str(tmp_path)!r})",
        "retina.pipeline.run(plan)",
    ]


def test_the_concatenated_echoes_form_a_valid_script(app_echo, raws_mono, tmp_path):
    app, echoes = app_echo
    inventory = app.pipeline.scan(raws_mono)
    app.pipeline.plan(inventory, "auto", output_dir=str(tmp_path))

    compile("\n".join(echoes), "<script>", "exec")


def test_the_echoed_script_really_runs(app_echo, raws_mono, tmp_path, capsys):
    """The real parity test: replaying the echo must produce the same result."""
    import retina

    app, echoes = app_echo
    inventory = app.pipeline.scan(raws_mono)
    plan = app.pipeline.plan(inventory, "auto", output_dir=str(tmp_path / "gui"))
    expected = [p.split("/")[-1] for p in plan.results]

    namespace: dict = {"retina": retina}
    source = "\n".join(echoes).replace(str(tmp_path / "gui"), str(tmp_path / "console"))
    exec(compile(source, "<script>", "exec"), namespace)

    assert [p.split("/")[-1] for p in namespace["plan"].results] == expected


def test_the_force_option_shows_up_in_the_echo(app_echo, raws_mono, tmp_path):
    app, echoes = app_echo
    plan = app.pipeline.plan(app.pipeline.scan(raws_mono), "auto",
                             output_dir=str(tmp_path))
    app.pipeline.run(plan, force=True)

    assert echoes[-1] == "retina.pipeline.run(plan, force=True)"


def test_a_non_recursive_scan_shows_up_in_the_echo(app_echo, raws_mono):
    app, echoes = app_echo
    app.pipeline.scan(raws_mono, recursive=False)

    assert echoes[-1].endswith(", recursive=False)")


def test_the_list_of_presets_is_exposed(app_echo):
    app, echoes = app_echo

    assert {p["name"] for p in app.pipeline.presets()} == set(PRESETS)
    assert echoes == []  # a read echoes nothing


def test_the_facade_is_lazy_and_stable(app_echo):
    app, _ = app_echo

    assert app.pipeline is app.pipeline


def test_the_domain_stays_callable_without_an_application(raws_mono):
    """`import retina` is enough: the facade is a convenience, not a mandatory detour."""
    import retina

    assert len(retina.pipeline.scan(raws_mono)) == 20
