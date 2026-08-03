"""Process documentation — consistency, console parity (headless) and rendering.

Everything is verifiable **without a shell**: the documentation is domain data, consumed
identically by the console and by the GUI (cf. ARCHITECTURE.md, console/GUI parity).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import retina
from retina import documentation as D
from retina.resources.icons import registry as icons

ROOT = Path(__file__).resolve().parent.parent
ALL = sorted(retina.all_processes())
REFERENCE = ["HistogramTransformation", "PixelMath", "Deconvolution",
             "BackgroundExtraction", "Integration"]


# --- coverage & consistency ------------------------------------------------ #
@pytest.mark.parametrize("pid", ALL)
def test_bilingual_doc_exists(pid):
    for lang in ("fr", "en"):
        assert (D.doc_dir(pid) / f"{lang}.md").is_file(), f"{pid}: {lang}.md missing"


@pytest.mark.parametrize("pid", ALL)
def test_frontmatter_valid(pid):
    cls = retina.all_processes()[pid]
    for lang in ("fr", "en"):
        meta = D.doc_meta(pid, lang)
        assert meta.get("id") == pid, f"{pid}/{lang}: inconsistent frontmatter id"
        assert meta.get("category") == cls.category
        assert isinstance(meta.get("keywords", []), list)
        assert isinstance(meta.get("related", []), list)
        assert meta.get("title")


@pytest.mark.parametrize("pid", ALL)
def test_related_targets_exist(pid):
    registry = retina.all_processes()
    for lang in ("fr", "en"):
        for rel in D.doc_meta(pid, lang).get("related", []) or []:
            assert rel in registry, f"{pid}/{lang}: 'related' points at unknown {rel!r}"


@pytest.mark.parametrize("pid", ALL)
def test_related_is_the_same_in_both_languages(pid):
    """It is navigation, not prose: a reader must not find a neighbour in one language and
    not in the other."""
    assert (D.doc_meta(pid, "en").get("related") or []) == (
        D.doc_meta(pid, "fr").get("related") or []
    ), f"{pid}: 'related' differs between languages"


@pytest.mark.parametrize("pid", ALL)
def test_icon_resolves_to_file(pid):
    assert D.icon_path(pid).is_file()


def test_all_referenced_icons_vendored():
    for name in icons.referenced_names():
        assert (D._ICON_LIB / f"{name}.svg").is_file(), f"icon {name} not vendored"


# --- console parity (headless) --------------------------------------------- #
def test_console_doc_callable():
    md = retina.doc("HistogramTransformation")
    assert isinstance(md, str) and len(md) > 100
    assert "## " in md  # it does have sections


def test_process_classmethod_doc():
    from retina import HistogramTransformation

    assert HistogramTransformation.doc("fr").strip()
    # also works through an instance
    assert HistogramTransformation().doc("en").strip()


def test_unknown_process_raises():
    with pytest.raises(KeyError):
        D.doc_markdown("NoSuchProcess")


def test_language_fallback(tmp_path, monkeypatch):
    # a process available in a single language must fall back to that one
    pid = "HistogramTransformation"
    assert D.doc_path(pid, "en") is not None
    # asking for a missing language ('xx') falls back to fr/en
    assert D.doc_path(pid, "xx") is not None


# --- HTML rendering --------------------------------------------------------- #
def _markdown_available() -> bool:
    try:
        import markdown  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.skipif(not _markdown_available(), reason="markdown not installed")
@pytest.mark.parametrize("pid", REFERENCE)
def test_render_page_reference(pid):
    html = D.render_page(pid, "fr", theme="dark")
    assert "<!DOCTYPE html>" in html
    assert "katex.min.css" in html and "renderMathInElement" in html
    assert "doc-header" in html
    assert "<svg" in html  # inline icon


@pytest.mark.skipif(not _markdown_available(), reason="markdown not installed")
def test_render_index():
    html = D.render_index(theme="light")
    assert "retina-doc://" in html
    for pid in REFERENCE:
        assert pid in html


# --- completeness gate (all written, no TODO marker left) ------------------ #
@pytest.mark.parametrize("pid", ALL)
def test_doc_has_no_todo(pid):
    """Every process is fully written (no residual TODO marker left)."""
    for lang in ("fr", "en"):
        assert "TODO" not in D.doc_markdown(pid, lang), f"{pid}/{lang}: stub not written"


# --- guides (pages that are not processes) --------------------------------- #
GUIDES = D.guides()


def test_there_is_at_least_one_discovery_walkthrough():
    """The docs used to be a catalog only: you got in only if you already knew what to look
    for."""
    assert "_guides/getting-started" in GUIDES


@pytest.mark.parametrize("gid", GUIDES)
def test_a_guide_is_bilingual_like_everything_else(gid):
    for lang in ("fr", "en"):
        assert (D.doc_dir(gid) / f"{lang}.md").is_file(), f"{gid}: {lang}.md missing"


@pytest.mark.parametrize("gid", GUIDES)
def test_a_guide_frontmatter_is_consistent(gid):
    registry = retina.all_processes()
    for lang in ("fr", "en"):
        meta = D.doc_meta(gid, lang)
        assert meta.get("id") == gid, f"{gid}/{lang}: inconsistent frontmatter id"
        assert meta.get("title")
        assert meta.get("brief")
        # The reading order of a walkthrough is not the alphabetical order of its folders.
        assert isinstance(meta.get("order"), int), f"{gid}/{lang}: 'order' missing or not an int"
        for rel in meta.get("related", []) or []:
            assert rel in registry, f"{gid}/{lang}: 'related' points at unknown {rel!r}"


@pytest.mark.parametrize("gid", GUIDES)
def test_a_guide_is_fully_written(gid):
    for lang in ("fr", "en"):
        assert "TODO" not in D.doc_markdown(gid, lang), f"{gid}/{lang}: stub not written"


@pytest.mark.parametrize("gid", GUIDES)
def test_a_guide_icon_resolves(gid):
    assert D.icon_path(gid).is_file()


@pytest.mark.parametrize("gid", GUIDES)
def test_the_internal_links_of_a_guide_point_at_real_pages(gid):
    """A dead `retina-doc://` would silently send the reader back to the home page — worse
    than an error."""
    import re

    registry = retina.all_processes()
    for lang in ("fr", "en"):
        for target in re.findall(r"retina-doc://([\w/-]+)", D.doc_markdown(gid, lang)):
            assert target in registry or target in GUIDES, (
                f"{gid}/{lang}: unknown target {target!r}")


def test_a_guide_reads_in_the_console_like_a_process():
    """Parity: documentation is domain data, not a screen."""
    text = retina.doc("_guides/getting-started")

    assert "## " in text and len(text) > 500


def test_an_identifier_that_walks_up_the_tree_is_refused():
    """The identifier now comes from a URL and may contain a slash."""
    for hostile in ("../../../etc/passwd", "_guides/../../secret", "/etc/passwd"):
        assert D.doc_path(hostile) is None
        with pytest.raises(KeyError):
            D.doc_markdown(hostile)


@pytest.mark.skipif(not _markdown_available(), reason="markdown not installed")
def test_a_guide_page_renders_like_a_process_page():
    html = D.render_page("_guides/getting-started", "fr", theme="dark")

    assert "<!DOCTYPE html>" in html
    assert "doc-header" in html and "<svg" in html
    assert "Premiers pas" in html  # the title of the French page being rendered


@pytest.mark.skipif(not _markdown_available(), reason="markdown not installed")
def test_the_index_shows_the_guides_before_the_catalog():
    """Whoever arrives without knowing what to look for needs a walkthrough, not 136
    thumbnails."""
    html = D.render_index(theme="dark", lang="en")

    assert "retina-doc://_guides/getting-started" in html
    assert html.index("_guides/getting-started") < html.index("HistogramTransformation")


# --- figures (generated by scripts/gen_doc_figures.py) --------------------- #
import re  # noqa: E402

FIGURE_RE = re.compile(r"!\[([^\]]*)\]\((figures/[^)]+)\)")
#: Per-image ceiling and total budget. The docs ship inside the wheel; PixInsight's 184 MB of
#: documentation is the cautionary tale, and a budget nobody enforces is a wish.
MAX_FIGURE_BYTES = 200 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
PAGES = ALL + GUIDES


@pytest.mark.parametrize("page_id", PAGES)
def test_every_referenced_figure_exists_with_alt_text(page_id):
    for lang in ("fr", "en"):
        for alt, relative in FIGURE_RE.findall(D.doc_markdown(page_id, lang)):
            assert alt.strip(), f"{page_id}/{lang}: figure {relative} has no alt text"
            assert (D.doc_dir(page_id) / relative).is_file(), (
                f"{page_id}/{lang}: missing figure {relative}")


@pytest.mark.parametrize("page_id", PAGES)
def test_no_orphan_figure(page_id):
    """A figure no page shows is dead weight in the wheel — and usually a rename left over."""
    folder = D.doc_dir(page_id) / "figures"
    if not folder.is_dir():
        return
    referenced = set()
    for lang in ("fr", "en"):
        referenced |= {rel for _, rel in FIGURE_RE.findall(D.doc_markdown(page_id, lang))}
    for image in folder.iterdir():
        if image.is_file():
            assert f"figures/{image.name}" in referenced, f"{page_id}: {image.name} unused"


@pytest.mark.parametrize("page_id", PAGES)
def test_a_figure_stays_under_its_ceiling(page_id):
    folder = D.doc_dir(page_id) / "figures"
    if not folder.is_dir():
        return
    for image in folder.iterdir():
        if image.is_file():
            size = image.stat().st_size
            assert size <= MAX_FIGURE_BYTES, (
                f"{page_id}/{image.name}: {size / 1024:.0f} kB over the "
                f"{MAX_FIGURE_BYTES / 1024:.0f} kB ceiling")


def test_the_figures_stay_within_the_wheel_budget():
    total = sum(p.stat().st_size for p in D._DOC.glob("*/figures/*") if p.is_file())
    assert total <= MAX_TOTAL_BYTES, f"figures total {total / 1024 / 1024:.1f} MB"


def test_figures_are_shown_in_both_languages():
    """A figure in one language only is a translation that fell behind, not a choice."""
    for pid in ALL:
        counts = {
            lang: len(FIGURE_RE.findall(D.doc_markdown(pid, lang))) for lang in ("fr", "en")
        }
        assert counts["fr"] == counts["en"], f"{pid}: {counts}"


@pytest.mark.skipif(not _markdown_available(), reason="markdown not installed")
def test_a_figure_is_rebased_on_the_media_route():
    """In the viewer the page is written into an iframe, where a relative `src` would resolve
    against the application and 404."""
    html = D.render_page("Deconvolution", "en", media_base="/api/doc-media/Deconvolution/")

    assert 'src="/api/doc-media/Deconvolution/figures/before.webp"' in html
    # Without a base, the Markdown's own relative path is left untouched.
    assert 'src="figures/before.webp"' in D.render_page("Deconvolution", "en")


@pytest.mark.skipif(not _markdown_available(), reason="markdown not installed")
def test_rebasing_leaves_absolute_urls_and_anchors_alone():
    html = D.render_page("Deconvolution", "en", media_base="/api/doc-media/Deconvolution/")

    assert "/api/doc-media//api/" not in html and "/api/doc-media/http" not in html
    # The table of contents keeps working: a `<base>` tag would have sent its anchors out of
    # the frame, which is why the rewrite targets `src` only.
    assert "/api/doc-media/#" not in html


# --- the console section (generated from the registry) --------------------- #
@pytest.mark.skipif(not _markdown_available(), reason="markdown not installed")
def test_a_process_page_ends_on_its_console_equivalent():
    """Console/GUI parity is the founding pillar; the reference said so nowhere."""
    html = D.render_page("PixelMath", "en")

    assert ">Console<" in html
    assert "codehilite" in html  # the snippet is a highlighted Python block
    # The code itself is asserted on the Markdown: in the HTML, Pygments has cut it into
    # `<span>`s, so no source line survives as a contiguous string.
    markdown = D._console_markdown("PixelMath", "en", "")
    assert "from retina import app, PixelMath" in markdown
    assert "app.run(PixelMath(" in markdown


def test_the_console_snippet_names_every_parameter():
    """Generated from the schema, so it cannot describe a signature the code no longer has."""
    markdown = D._console_markdown("Deconvolution", "en", "")

    for param in retina.all_processes()["Deconvolution"].parameters:
        assert f"{param.id}=" in markdown


def test_a_hand_written_console_section_wins():
    """Three pages show how to consume `.result`, which no generator can guess."""
    body = D.doc_markdown("MosaicPlanner", "en")

    assert "## Console" in body
    assert D._console_markdown("MosaicPlanner", "en", body) == ""


def test_a_guide_has_no_console_section():
    assert D._console_markdown("_guides/getting-started", "en", "") == ""


# --- search ----------------------------------------------------------------- #
def test_search_ranks_the_page_that_is_about_the_word_first():
    assert D.search("gradient", "en")[0]["page_id"].startswith("Gradient")


def test_search_folds_accents_because_a_search_box_is_typed_at_speed():
    """Half the catalogue is French, and a query loses its accents before its author does."""
    assert D.search("etoiles", "fr"), "accent-free French query found nothing"
    ids = {hit["page_id"] for hit in D.search("etoiles", "fr")}
    assert ids & {"StarMask", "StarRemoval", "StarReduction"}


def test_search_requires_every_term():
    """An `or` search answers a two-word query with the whole catalogue."""
    assert not D.search("deconvolution zzzznotaword", "en")


def test_search_finds_guides_too():
    hits = D.search("premiers pas", "fr")

    assert any(hit["is_guide"] for hit in hits)


def test_search_is_reachable_from_the_console():
    hits = retina.doc_search("deconvolution", "en", limit=3)

    assert 1 <= len(hits) <= 3
    assert hits[0]["snippet"] and hits[0]["title"]


def test_an_empty_query_returns_nothing_rather_than_everything():
    assert D.search("", "en") == [] and D.search("  a ", "en") == []


# --- the partition: illustrated, or explained ------------------------------ #
def _figure_specs() -> set[str]:
    folder = ROOT / "scripts" / "doc_figures"
    return {p.stem for p in folder.glob("*.py") if not p.name.startswith("_")}


def _not_illustrated() -> dict[str, str]:
    import importlib.util

    path = ROOT / "scripts" / "doc_figures" / "_catalogue.py"
    spec = importlib.util.spec_from_file_location("doc_figures_catalogue", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NOT_ILLUSTRATED


def test_every_process_is_illustrated_or_explained():
    """No silent gap. A process with no figure and no stated reason is indistinguishable, six
    months later, from one nobody has got to yet — so the catalogue has to say which."""
    illustrated, explained = _figure_specs(), set(_not_illustrated())

    assert not (illustrated & explained), (
        f"both illustrated and explained away: {sorted(illustrated & explained)}")
    assert not (illustrated - set(ALL)), f"figure spec for no process: {illustrated - set(ALL)}"
    assert not (explained - set(ALL)), f"reason for no process: {explained - set(ALL)}"
    assert not (set(ALL) - illustrated - explained), (
        "no figure and no reason: " + ", ".join(sorted(set(ALL) - illustrated - explained)))


def test_a_stated_reason_actually_says_something():
    for pid, reason in _not_illustrated().items():
        assert len(reason) > 12, f"{pid}: {reason!r} is not a reason"


@pytest.mark.parametrize("pid", ALL)
def test_a_spec_and_its_figures_agree(pid):
    """A spec that ran must have left figures, and figures must come from a spec."""
    has_figures = (D.doc_dir(pid) / "figures").is_dir()
    if pid in _not_illustrated():
        assert not has_figures, f"{pid}: listed as not illustrated but has figures"
