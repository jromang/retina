"""Documentation service: servable assets, internal links, traversal guard.

The sensitive point is the **asset base**. The HTML the domain produces references KaTeX and
its stylesheet as ``file://`` — fine for a page opened from disk, but something a browser
refuses in a page served over ``http://`` (mixed schemes). Without the ``assets_base``
parameter, the documentation would render without maths and without style, silently.
"""

from __future__ import annotations

import pytest
from retina import documentation as doc


async def _fetch(client, path: str):
    return await client.get(path, headers={"X-Retina-Token": client.retina.token})


def test_the_default_stays_file_for_a_standalone_page():
    """The default serves `scripts/gen_process_docs.py`, which writes HTML opened from disk.

    That is the only reason it still exists: the web shell always passes ``assets_base``.
    Keeping it avoids breaking offline documentation generation.
    """
    html = doc.render_page("Invert")
    assert "file:///" in html


def test_the_asset_base_can_be_replaced():
    html = doc.render_page("Invert", assets_base="/api/doc-assets/")
    assert "/api/doc-assets/katex/katex.min.css" in html
    assert "file:///" not in html, "a file:// sub-resource would be blocked in a browser"


async def test_a_process_page_is_served(client):
    response = await _fetch(client, "/api/doc/GaussianConvolution")
    assert response.status == 200
    assert response.content_type == "text/html"
    body = await response.text()
    assert "/api/doc-assets/" in body
    assert "file:///" not in body


async def test_the_index_lists_the_processes(client):
    response = await _fetch(client, "/api/doc/")
    body = await response.text()
    # Internal links keep the custom scheme, which the frontend intercepts.
    assert "retina-doc://" in body
    # The index must apply `assets_base` just like the process pages: a `file://`
    # sub-resource on a page served over HTTP is refused by the browser, and the index
    # would render unstyled — silently. (`render_index` had forgotten to pass it on.)
    assert "/api/doc-assets/doc.css" in body
    assert "file:///" not in body, "a file:// sub-resource would be blocked in a browser"


async def test_a_process_without_docs_falls_back_to_the_index(client):
    """Deliberate fallback: having no documentation is not a blocking error."""
    response = await _fetch(client, "/api/doc/NoSuchProcess")
    assert response.status == 200
    assert "retina-doc://" in await response.text()


async def test_the_assets_are_served(client):
    response = await _fetch(client, "/api/doc-assets/doc.css")
    assert response.status == 200
    assert response.content_type == "text/css"


@pytest.mark.parametrize(
    "path",
    ["/api/doc-assets/../../app.py", "/api/doc-assets/..%2F..%2Fapp.py"],
)
async def test_directory_traversal_is_refused(client, path):
    """A `..` in the URL must not escape the assets folder."""
    response = await _fetch(client, path)
    assert response.status in (400, 403, 404)


async def test_the_icons_are_served(client):
    response = await _fetch(client, "/api/icons/wand.svg")
    assert response.status == 200
    assert response.content_type == "image/svg+xml"
    # `currentColor`: the hue comes from the CSS, not the file — that is what lets the same
    # icon be used in a light toolbar and a dark one.
    assert "currentColor" in await response.text()


async def test_an_unknown_icon_falls_back_to_the_default_icon(client):
    """The domain has a deliberate fallback (``documentation.icon_svg_by_name``).

    A process with no icon of its own — there are some, the registry does not cover all 115 —
    must show the generic icon, not a broken image. Serving a 404 here would force every
    caller to handle the case, when the domain has already settled it.
    """
    response = await _fetch(client, "/api/icons/does-not-exist.svg")
    assert response.status == 200
    default = await _fetch(client, f"/api/icons/{doc._icons.DEFAULT_ICON}.svg")
    assert await response.text() == await default.text()
