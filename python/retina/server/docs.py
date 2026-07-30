"""HTTP service for the documentation and the icons.

The documentation is already rendered to HTML by :mod:`retina.documentation` (Markdown +
KaTeX + Pygments): there is nothing to rewrite, only to serve. Two adaptations are needed:

- the assets (KaTeX, style sheet) are referenced as ``file://`` for an embedded web view of a
  page opened from disk; a browser refuses those sub-resources over ``http://``. Hence
  ``assets_base``, added to the core — see ``documentation._assets_base``.
- the index's internal links use the ``retina-doc://<pid>`` scheme, which the frontend
  intercepts to navigate without the network. The contract is kept as is.

The **guides** (``_guides/<slug>``, see :mod:`retina.documentation`) go through the same
route: their identifier contains a slash, which a client encodes as ``%2F`` and which aiohttp
hands back decoded in ``match_info``. The explicit ``/api/doc/_guides/{slug}`` route is there
for the other form — a URL typed by hand, a copied link — so that both spellings lead to the
same page rather than only one, at the mercy of the encoding.
"""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from .. import documentation as doc

ASSETS_BASE = "/api/doc-assets/"

_MIME = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".svg": "image/svg+xml",
}


class DocHandlers:
    """Documentation routes. No state: everything comes from the resource package."""

    def add_routes(self, router: web.UrlDispatcher) -> None:
        router.add_get("/api/doc/", self.index)
        # Before the generic route: aiohttp tries resources in the order they were added.
        router.add_get(f"/api/doc/{doc.GUIDE_PREFIX}/{{slug}}", self.guide)
        router.add_get("/api/doc/{process_id}", self.page)
        router.add_get("/api/doc-assets/{path:.*}", self.asset)
        router.add_get("/api/icons/{name}.svg", self.icon)

    async def index(self, request: web.Request) -> web.Response:
        # An empty string and not `DEFAULT_LANG`: it is `doc.default_lang()` that decides,
        # hence the application's language, when the client asks for nothing.
        lang = request.query.get("lang", "")
        html = doc.render_index(lang=lang, assets_base=ASSETS_BASE)
        return web.Response(text=html, content_type="text/html")

    async def page(self, request: web.Request) -> web.Response:
        return self._render(request.match_info["process_id"], request)

    async def guide(self, request: web.Request) -> web.Response:
        """A guide reached by its plain path (``/api/doc/_guides/getting-started``)."""
        return self._render(f"{doc.GUIDE_PREFIX}/{request.match_info['slug']}", request)

    def _render(self, page_id: str, request: web.Request) -> web.Response:
        # An empty string and not `DEFAULT_LANG`: it is `doc.default_lang()` that decides,
        # hence the application's language, when the client asks for nothing.
        lang = request.query.get("lang", "")
        try:
            html = doc.render_page(page_id, lang, assets_base=ASSETS_BASE)
        except KeyError:
            # A process without documentation is not an error: we return the home page,
            # and the home page is always a useful answer.
            html = doc.render_index(lang=lang, assets_base=ASSETS_BASE)
        return web.Response(text=html, content_type="text/html")

    async def asset(self, request: web.Request) -> web.FileResponse:
        relative = request.match_info["path"]
        root = doc._ASSETS.resolve()
        target = (root / relative).resolve()
        # Traversal guard: a `..` in the URL must not escape the assets folder.
        if root not in target.parents or not target.is_file():
            raise web.HTTPNotFound(text=f"unknown asset: {relative}")
        return web.FileResponse(
            target, headers={"Content-Type": _MIME.get(target.suffix, "application/octet-stream")}
        )

    async def icon(self, request: web.Request) -> web.Response:
        """Tabler icon by name. The SVGs use ``currentColor``: the color comes from CSS."""
        name = request.match_info["name"]
        try:
            svg = doc.icon_svg_by_name(name)
        except (KeyError, OSError, FileNotFoundError):
            raise web.HTTPNotFound(text=f"unknown icon: {name}") from None
        return web.Response(
            text=svg,
            content_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )


def assets_root() -> Path:
    return doc._ASSETS
