"""Validation for structured change reports (spec section 8).

Rejects malformed output instead of quietly repairing substantive claims.
Every factual claim must carry citations or be explicitly marked
unsupported — enforced here, not by convention.
"""
from __future__ import annotations

CHANGE_TYPES = {
    "new_document", "text_modified", "metadata_modified",
    "possible_amendment", "corrigendum", "unknown",
}
CLAIM_TYPES = {"source_fact", "textual_comparison", "interpretation"}
REVIEW_STATUSES = {"pending", "approved", "rejected", "needs_changes"}


class ReportValidationError(ValueError):
    """Raised when a report (or model output) violates the schema."""


def _require(mapping: dict, key: str, types) -> None:
    if key not in mapping:
        raise ReportValidationError(f"missing required key: {key}")
    if not isinstance(mapping[key], types):
        raise ReportValidationError(
            f"key {key!r} must be {types}, got {type(mapping[key]).__name__}"
        )


def validate_report(report: dict) -> None:
    """Validate a change-report dict. Raises ReportValidationError."""
    if not isinstance(report, dict):
        raise ReportValidationError("report must be a mapping")
    for key in ("document_title", "issuing_authority", "jurisdiction",
                "document_type", "official_source_url", "change_type",
                "summary", "review_status"):
        _require(report, key, str)
    if report["change_type"] not in CHANGE_TYPES:
        raise ReportValidationError(
            f"unknown change_type: {report['change_type']!r}")
    if report["review_status"] not in REVIEW_STATUSES:
        raise ReportValidationError(
            f"unknown review_status: {report['review_status']!r}")
    for key in ("textual_changes", "potentially_affected_groups",
                "related_documents", "claims", "warnings", "affected_sections"):
        _require(report, key, list)
    for change in report["textual_changes"]:
        for key in ("description", "old_text", "new_text",
                    "source_locator", "confidence"):
            _require(change, key, str)
        if change["confidence"] not in ("high", "medium", "low"):
            raise ReportValidationError("bad confidence value")
    _require(report, "commencement", dict)
    for key in ("statement", "date", "source_locator", "verification_status"):
        if key not in report["commencement"]:
            raise ReportValidationError(f"commencement missing {key}")
    for claim in report["claims"]:
        for key in ("claim", "claim_type", "citation_ids",
                    "verification_status"):
            if key not in claim:
                raise ReportValidationError(f"claim missing {key}")
        if claim["claim_type"] not in CLAIM_TYPES:
            raise ReportValidationError(
                f"unknown claim_type: {claim['claim_type']!r}")
        if not claim["citation_ids"] and not claim.get("unsupported", False):
            raise ReportValidationError(
                f"claim has no citations and is not marked unsupported: "
                f"{claim['claim'][:80]!r}")
    citations = report.get("citations", [])
    if not isinstance(citations, list):
        raise ReportValidationError("citations must be a list")
    known_ids = {c.get("citation_id") for c in citations
                 if isinstance(c, dict)}
    for claim in report["claims"]:
        for cid in claim["citation_ids"]:
            if cid not in known_ids:
                raise ReportValidationError(
                    f"claim references unknown citation {cid!r}")
