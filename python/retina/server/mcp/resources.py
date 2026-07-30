"""MCP resources — process documentation, addressable by URI.

An agent can read ``retina://doc/HistogramTransformation`` without spending a tool call. The
same documentation stays attached to ``describe_process``: many MCP clients ignore resources,
and a capability that existed only there would be invisible to them.

English is deliberate (``lang="en"``): see the header of :mod:`~retina.server.mcp.tools`.
"""

from __future__ import annotations

import json

SCHEME = "retina://doc/"
INDEX_URI = "retina://doc/index"


def list_resources() -> list[dict]:
    return [
        {
            "uri": INDEX_URI,
            "name": "process-index",
            "title": "Process catalogue",
            "description": "Every available process, grouped by category.",
            "mimeType": "application/json",
        }
    ]


def list_templates() -> list[dict]:
    return [
        {
            "uriTemplate": "retina://doc/{process_id}",
            "name": "process-documentation",
            "title": "Process documentation",
            "description": "Reference documentation for one process, in Markdown.",
            "mimeType": "text/markdown",
        }
    ]


def read_resource(uri: str) -> dict | None:
    from ...documentation import doc_index, doc_markdown, has_doc

    if uri == INDEX_URI:
        return {
            "uri": uri,
            "mimeType": "application/json",
            "text": json.dumps(doc_index(), indent=2, ensure_ascii=False),
        }
    if not uri.startswith(SCHEME):
        return None
    process_id = uri[len(SCHEME):]
    if not process_id or not has_doc(process_id):
        return None
    return {"uri": uri, "mimeType": "text/markdown", "text": doc_markdown(process_id, "en")}
