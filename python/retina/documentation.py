"""Documentation — loading, metadata, HTML rendering, icons.

A **domain** module (headless, no shell): it is the single source of truth for the docs,
which the console and the GUI consume the same way (console/GUI parity, see
ARCHITECTURE.md).

- :func:`doc_markdown` / :func:`doc_meta` — raw text + frontmatter (pure Python reading,
  depends only on PyYAML). This is what ``retina.doc(process_id)`` returns in the console.
- :func:`render_markdown` / :func:`render_page` / :func:`render_index` — full HTML rendering
  (Markdown → HTML + KaTeX for the math + Pygments for the code), for the doc viewer.
  **Lazy** import of ``markdown``: absent → raw reading is still possible.
- :func:`icon_name` / :func:`icon_path` / :func:`icon_svg` — a process's icon.

Location of the sources: ``retina/resources/doc/<ProcessId>/{fr,en}.md`` and the embedded
assets (``_assets/``) — everything is packaged in the wheel (offline operation).

# The pages that are not processes

The docs were long only a catalogue: one page per process, reached from its panel. What was
missing was what a newcomer looks for first — a *walkthrough*, which speaks of no process in
particular. Hence the **guides**, filed under ``doc/_guides/<slug>/{en,fr}.md`` and addressed
by the identifier ``_guides/<slug>``.

The prefix is not decorative: a ``process_id`` is a Python class name, so it can neither
start with an underscore nor contain a slash. Collision is impossible by construction, and
the same identifier goes through everything that already existed — ``doc_markdown``,
``render_page``, the ``retina-doc://`` links and the ``/api/doc/<id>`` route. No second
plumbing to write, hence none to let diverge.

The counterpart not to forget: this identifier now comes from a URL **and** contains a slash,
which would open the door to a ``..`` climbing the tree. :func:`doc_dir` therefore constrains
the path under ``resources/doc/``.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

from .i18n import translate as _t
from .resources.icons import registry as _icons

_RES = Path(__file__).resolve().parent / "resources"
_DOC = _RES / "doc"
_ASSETS = _DOC / "_assets"
_ICON_LIB = _RES / "icons" / "lib"

#: Language of last resort, and base language of the catalogues. The documentation itself has
#: always been bilingual (``resources/doc/<Process>/{en,fr}.md``): all that was missing was
#: wiring the user's choice to it.
DEFAULT_LANG = "en"
LANGUAGES = ("en", "fr")

#: Prefix of the non-process pages (see the module header). A ``process_id`` being a class
#: name, it cannot start with an underscore: no collision is possible.
GUIDE_PREFIX = "_guides"


def default_lang() -> str:
    """The language to serve for want of an explicit request — the application's.

    Resolved on **every call** and not frozen as an argument default: a default value is
    evaluated when the module is imported, hence before the user's preference is known, and
    the documentation would have stayed English for everybody.
    """
    from . import i18n

    lang = i18n.effective_language()
    return lang if lang in LANGUAGES else DEFAULT_LANG


# --------------------------------------------------------------------------- #
# Raw loading (headless, without markdown)                                     #
# --------------------------------------------------------------------------- #
def doc_dir(page_id: str) -> Path:
    """Folder of a page — a process (``PixelMath``) or a guide (``_guides/<slug>``).

    The path is **constrained** under ``resources/doc/``. As long as an identifier was a
    class name, the question did not arise; since the guides it contains a slash and comes
    from a URL, so a ``..`` would climb the disk. An identifier outside the folder raises,
    and the caller treats it as a missing page.
    """
    target = (_DOC / page_id).resolve()
    if _DOC not in target.parents:
        raise KeyError(_t("documentation page outside the doc tree: {id!r}").format(id=page_id))
    return target


def is_guide(page_id: str) -> bool:
    """True for a non-process page (``_guides/<slug>``)."""
    return str(page_id).startswith(GUIDE_PREFIX + "/")


def guides() -> list[str]:
    """Ids of the available guides, in reading order.

    The order comes from the frontmatter's ``order`` field and not from the folder name: a
    walkthrough is read in a pedagogical order, which the alphabet ignores. A page without
    ``order`` goes last, which lets one add a guide without renumbering the others.
    """
    base = _DOC / GUIDE_PREFIX
    if not base.is_dir():
        return []
    ids = [
        f"{GUIDE_PREFIX}/{d.name}"
        for d in sorted(base.iterdir())
        if d.is_dir() and any((d / f"{code}.md").is_file() for code in LANGUAGES)
    ]

    def rank(page_id: str) -> tuple[int, str]:
        try:
            return int(doc_meta(page_id).get("order", 999)), page_id
        except (KeyError, TypeError, ValueError):
            return 999, page_id

    return sorted(ids, key=rank)


def _lang_order(lang: str) -> tuple[str, ...]:
    lang = (lang or default_lang()).lower()
    rest = [x for x in LANGUAGES if x != lang]
    return (lang, *rest)


def doc_path(page_id: str, lang: str = "") -> Path | None:
    """Path of the ``<lang>.md`` file (falling back to the other language), or None."""
    try:
        d = doc_dir(page_id)
    except KeyError:
        return None
    for code in _lang_order(lang):
        p = d / f"{code}.md"
        if p.is_file():
            return p
    return None


def has_doc(process_id: str) -> bool:
    return doc_path(process_id) is not None


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a YAML frontmatter (``--- … ---`` at the top) from the Markdown body."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            meta = yaml.safe_load(raw) or {}
            if not isinstance(meta, dict):
                meta = {}
            return meta, body
    return {}, text


def _read(process_id: str, lang: str) -> tuple[dict, str]:
    p = doc_path(process_id, lang)
    if p is None:
        raise KeyError(_t("No documentation page for {id!r}").format(id=process_id))
    return _split_frontmatter(p.read_text(encoding="utf-8"))


def doc_markdown(process_id: str, lang: str = "") -> str:
    """Markdown body of the docs (frontmatter stripped). ``KeyError`` if absent.

    This is the console entry point: ``retina.doc("PixelMath")``, or
    ``retina.doc("_guides/getting-started")`` for a guide.
    """
    return _read(process_id, lang)[1]


def doc_meta(process_id: str, lang: str = "") -> dict:
    """Parsed frontmatter (id, title, brief, keywords, related, icon, references…)."""
    return _read(process_id, lang)[0]


@functools.lru_cache(maxsize=512)
def doc_keywords(process_id: str, lang: str) -> tuple[str, ...]:
    """Search terms of a page, from its frontmatter — what a user is likely to type.

    The explorer's search box matched the ``process_id`` and nothing else, so "gradient"
    found `GradientCorrection` but not `BackgroundExtraction`, and "stretch" missed
    `AutoHistogram`. The vocabulary an astrophotographer uses is already written down, once,
    in each page's ``keywords`` — and in their own language, which is why ``lang`` is part of
    the key rather than resolved inside.

    An undocumented process (a third-party one) simply has none.
    """
    try:
        raw = _read(process_id, lang)[0].get("keywords", ())
    except (KeyError, OSError):
        return ()
    if isinstance(raw, str):
        raw = [raw]
    return tuple(str(k) for k in raw)


# --------------------------------------------------------------------------- #
# Icons                                                                        #
# --------------------------------------------------------------------------- #
@functools.cache
def _category_of(process_id: str) -> str:
    """A process's category (lazy import of the registry, with no shell dependency)."""
    try:
        from .process.registry import all_processes

        cls = all_processes().get(process_id)
        return getattr(cls, "category", "") if cls else ""
    except Exception:
        return ""


def icon_name(process_id: str, *, override: str = "") -> str:
    """A process's effective icon name (frontmatter > process > category > default)."""
    if not override:
        try:
            override = str(doc_meta(process_id).get("icon", "") or "")
        except KeyError:
            override = ""
    return _icons.resolve(process_id, _category_of(process_id), override)


def icon_path(process_id: str, *, override: str = "") -> Path:
    """Path of the icon's SVG (falls back to the default icon if the name is missing)."""
    name = icon_name(process_id, override=override)
    p = _ICON_LIB / f"{name}.svg"
    if not p.is_file():
        p = _ICON_LIB / f"{_icons.DEFAULT_ICON}.svg"
    return p


def icon_svg(process_id: str, *, override: str = "") -> str:
    """SVG content (`<svg …>`) of a process's icon."""
    return icon_path(process_id, override=override).read_text(encoding="utf-8")


def icon_svg_by_name(name: str) -> str:
    p = _ICON_LIB / f"{name}.svg"
    if not p.is_file():
        p = _ICON_LIB / f"{_icons.DEFAULT_ICON}.svg"
    return p.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Index (the viewer's home page)                                               #
# --------------------------------------------------------------------------- #
def doc_index() -> dict[str, list[str]]:
    """``{category: [process_id, …]}``, sorted — for the docs home page."""
    from .process.registry import all_processes

    out: dict[str, list[str]] = {}
    for pid, cls in sorted(all_processes().items()):
        out.setdefault(getattr(cls, "category", "General"), []).append(pid)
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- #
# HTML rendering (viewer) — lazy import of markdown/pygments                   #
# --------------------------------------------------------------------------- #
def _assets_base(override: str | None = None) -> str:
    """Prefix of the assets (KaTeX, CSS) in the produced HTML.

    By default a ``file://`` URL, which suits an embedded web view loading the page from
    disk. A web shell, for its part, serves the page over ``http://``: a browser then refuses
    ``file://`` sub-resources (mixed schemes), and the page would display without math or
    style. Hence this parameter — the only change the web migration imposes on the core.
    """
    return override if override is not None else _ASSETS.as_uri() + "/"


@functools.lru_cache(maxsize=1)
def _pygments_css() -> str:
    from pygments.formatters import HtmlFormatter

    light = HtmlFormatter(style="default").get_style_defs(".codehilite")
    dark = HtmlFormatter(style="monokai").get_style_defs(".codehilite")
    dark_attr = HtmlFormatter(style="monokai").get_style_defs('[data-theme="dark"] .codehilite')
    return (
        f"{light}\n@media (prefers-color-scheme: dark){{{dark}}}\n{dark_attr}"
    )


def render_markdown(md_text: str) -> str:
    """Markdown → HTML fragment (math in KaTeX delimiters, code colored by Pygments)."""
    import markdown

    return markdown.markdown(
        md_text,
        extensions=[
            "extra",  # tables, fenced_code, def_list, footnotes…
            "sane_lists",
            "codehilite",
            "toc",
            "pymdownx.arithmatex",
        ],
        extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
            "pymdownx.arithmatex": {"generic": True},
        },
    )


def _header_html(process_id: str, meta: dict) -> str:
    title = meta.get("title") or process_id
    category = meta.get("category", "")
    brief = meta.get("brief", "")
    try:
        svg = icon_svg(process_id)
    except Exception:
        svg = ""
    chips = ""
    kws = meta.get("keywords") or []
    if kws:
        chips = '<div class="doc-chips">' + "".join(
            f'<span class="doc-chip">{_esc(str(k))}</span>' for k in kws
        ) + "</div>"
    cat = f'<div class="doc-category">{_esc(category)}</div>' if category else ""
    brief_html = f'<p class="doc-brief">{_esc(brief)}</p>' if brief else ""
    return (
        '<div class="doc-header">'
        f'<div class="doc-icon">{svg}</div>'
        f"<div><h1>{_esc(title)}</h1>{cat}</div>"
        "</div>"
        f"{brief_html}{chips}"
    )


def _page(
    body: str,
    *,
    theme: str,
    extra_class: str = "",
    assets_base: str | None = None,
    lang: str = "",
) -> str:
    base = _assets_base(assets_base)
    cls = ("doc " + extra_class).strip()
    # `lang` on the root tag: browsers use it for hyphenation and for speech synthesis, and
    # it read "fr" even on an English page.
    page_lang = _esc((lang or default_lang()).lower())
    return f"""<!DOCTYPE html>
<html lang="{page_lang}" data-theme="{_esc(theme)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="{base}katex/katex.min.css">
<link rel="stylesheet" href="{base}doc.css">
<style>{_pygments_css()}</style>
</head>
<body data-theme="{_esc(theme)}">
<div class="{cls}">
{body}
</div>
<script src="{base}katex/katex.min.js"></script>
<script src="{base}katex/auto-render.min.js"></script>
<script>
document.addEventListener("DOMContentLoaded", function () {{
  renderMathInElement(document.body, {{
    delimiters: [
      {{left: "$$", right: "$$", display: true}},
      {{left: "\\\\[", right: "\\\\]", display: true}},
      {{left: "\\\\(", right: "\\\\)", display: false}}
    ],
    throwOnError: false
  }});
}});
</script>
</body>
</html>"""


def render_page(
    process_id: str,
    lang: str = "",
    *,
    theme: str = "dark",
    assets_base: str | None = None,
) -> str:
    """Full HTML page of a process (header + rendered body).

    ``assets_base`` replaces the assets' ``file://`` prefix — necessary as soon as the page
    is served over HTTP rather than loaded from disk. See :func:`_assets_base`.
    """
    meta, body = _read(process_id, lang)
    meta.setdefault("category", _category_of(process_id))
    html = _header_html(process_id, meta) + render_markdown(body)
    return _page(html, theme=theme, assets_base=assets_base, lang=lang)


def _card(page_id: str, lang: str) -> str:
    """A clickable card of the index — the same shape for a guide and for a process."""
    try:
        svg = icon_svg(page_id)
    except Exception:
        svg = ""
    try:
        title = doc_meta(page_id, lang).get("title") or page_id
    except KeyError:
        title = page_id
    return (
        f'<a class="doc-card" href="retina-doc://{page_id}">'
        f'<span class="doc-icon">{svg}</span>'
        f'<span class="doc-card-title">{_esc(title)}</span></a>'
    )


def _section(title: str, cards: list[str]) -> str:
    return (f'<div class="doc-cat"><h2>{_esc(title)}</h2>'
            f'<div class="doc-grid">{"".join(cards)}</div></div>')


def render_index(
    *, theme: str = "dark", lang: str = "", assets_base: str | None = None
) -> str:
    """Home page: the guides, then every process by category.

    The guides come **before** the catalogue, and that is the only defensible order: whoever
    arrives here without knowing what to look for needs a walkthrough, not a wall of cards.
    Whoever knows what they are looking for scrolls down one line.
    """
    from .i18n import translate as _t

    # Translated into the **requested** language, not the application's: a page served with
    # `?lang=en` must be so entirely, title included. Without this parameter, the page mixed
    # an English body with a French title.
    page = lang or default_lang()
    index = doc_index()
    # Counted from the registry rather than written down. The figure appeared in three places
    # in prose, and all three said 136 while the catalogue had moved on: a number nobody can
    # forget to update is worth more than a number that is right today.
    total = sum(len(pids) for pids in index.values())
    lead = _t("Start with a guide, or pick one of the {count} processes.", page)
    parts = [f"<h1>{_esc(_t('Documentation', page))}</h1>",
             f'<p class="doc-brief">{_esc(lead.format(count=total))}</p>']
    guide_ids = guides()
    if guide_ids:
        parts.append(_section(_t("Guides", page), [_card(gid, lang) for gid in guide_ids]))
    for category, pids in index.items():
        parts.append(_section(category, [_card(pid, lang) for pid in pids]))
    return _page(
        "\n".join(parts),
        theme=theme,
        extra_class="doc-index",
        assets_base=assets_base,
        lang=lang,
    )


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# console alias: ``retina.doc(...)`` → raw Markdown text.
def doc(process_id: str, lang: str = "") -> str:
    return doc_markdown(process_id, lang)
