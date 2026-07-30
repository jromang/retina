"""``credits.*`` family of the protocol.

A facade over :mod:`retina.credits`. Nothing mutating, nothing to broadcast: the list does not
change during a session. The labels are **not** translated — they are project names, SPDX
expressions and URLs, that is to say identifiers. Only the notes, written by us, would be… and
they are not either: they live in a versioned manifest that has no catalogue. It is the same
trade-off as for the MCP tool descriptions.
"""

from __future__ import annotations

from .. import credits

CREDIT_METHODS: dict[str, bool] = {
    "credits.list": False,
    "credits.notice": False,
}


class CreditHandlers:
    def list(self) -> dict:
        """Every component, grouped by family, plus the per-family count."""
        return {
            "kinds": list(credits.KINDS),
            "components": [c.to_dict() for c in credits.all_credits()],
            "summary": credits.summary(),
        }

    def notice(self, id: str) -> str:
        """The full text of an embedded license."""
        return credits.notice(id)
