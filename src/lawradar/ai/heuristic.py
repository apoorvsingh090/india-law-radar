"""Default summariser: deterministic, no model, always available.

Returns the draft untouched (plus a provenance marker) so the system
produces and reviews reports with no LLM and no network. This is what
``reports summarise`` uses unless ``--ai`` with a configured command
is requested.
"""
from __future__ import annotations

from lawradar.ai.base import AISummariserError  # noqa: F401  (public re-export)


class HeuristicSummariser:
    """Pass-through summariser. Never invents, never fails on content."""

    name = "heuristic"

    def summarise(self, draft: dict, evidence: dict) -> dict:  # noqa: ARG002
        if not isinstance(draft, dict) or "summary" not in draft:
            raise AISummariserError("draft report missing summary")
        return {
            "summary": draft["summary"],
            "claims": [dict(c) for c in draft.get("claims", [])],
            "warnings": list(draft.get("warnings", [])) + [
                "summary produced by the deterministic heuristic "
                "(no LLM involved)"
            ],
        }
