"""Process documentation — consistency, console parity (headless) and rendering.

Everything is verifiable **without a shell**: the documentation is domain data, consumed
identically by the console and by the GUI (cf. ARCHITECTURE.md, console/GUI parity).
"""

from __future__ import annotations

import pytest
import retina
from retina import documentation as D
from retina.resources.icons import registry as icons

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
