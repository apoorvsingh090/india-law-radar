"""Reporting tests: schema validation + deterministic generation."""
import pytest

from lawradar.reporting.generate import build_report
from lawradar.reporting.schema import ReportValidationError, validate_report

DOC = {
    "title": "Sample Act",
    "issuing_authority": "Fixture Authority",
    "jurisdiction": "central",
    "document_type": "Act",
    "official_url": "https://example.invalid/sample",
}
OLD_V = {"id": 1, "version_number": 1, "retrieved_at": "2026-01-01T00:00:00Z",
         "extraction_status": "ok", "content_sha256": "a" * 64,
         "review_status": "pending", "parser_warnings": "[]"}
NEW_V = {"id": 2, "version_number": 2, "retrieved_at": "2026-02-01T00:00:00Z",
         "extraction_status": "ok", "content_sha256": "b" * 64,
         "review_status": "pending", "parser_warnings": "[]"}
OLD_TEXT = "Section 1\nFile within thirty days.\n"
NEW_TEXT = "Section 1\nFile within forty-five days.\nSection 2\nLate fee applies.\n"


def test_build_report_changed():
    report = build_report(DOC, OLD_V, NEW_V, OLD_TEXT, NEW_TEXT)
    assert report["change_type"] == "text_modified"
    assert report["review_status"] == "pending"
    assert "forty-five days" in "".join(
        c["new_text"] for c in report["textual_changes"])
    assert report["commencement"]["verification_status"] == "unverified"
    assert report["commencement"]["date"] is None  # unknown stays unknown
    assert report["published_date"] is None


def test_build_report_first_version():
    report = build_report(DOC, None, NEW_V, "", NEW_TEXT)
    assert report["change_type"] == "new_document"
    assert report["textual_changes"] == []


def test_build_report_withheld_without_evidence():
    bad = dict(NEW_V, extraction_status="failed", review_status="needs_review")
    report = build_report(DOC, OLD_V, bad, OLD_TEXT, "")
    assert report["change_type"] == "unknown"
    assert report["review_status"] == "needs_changes"
    assert report["warnings"]


def test_every_claim_has_citation():
    report = build_report(DOC, OLD_V, NEW_V, OLD_TEXT, NEW_TEXT)
    for claim in report["claims"]:
        assert claim["citation_ids"], f"unsupported claim: {claim['claim'][:60]}"
    validate_report(report)  # must not raise


def test_schema_rejects_unsupported_claim():
    report = build_report(DOC, OLD_V, NEW_V, OLD_TEXT, NEW_TEXT)
    report["claims"].append({
        "claim": "This provision applies to everyone.",
        "claim_type": "interpretation",
        "citation_ids": [],
        "verification_status": "unverified",
    })
    with pytest.raises(ReportValidationError, match="no citations"):
        validate_report(report)


def test_schema_rejects_bad_change_type_and_dangling_citation():
    report = build_report(DOC, OLD_V, NEW_V, OLD_TEXT, NEW_TEXT)
    report["change_type"] = "repealed_by_magic"
    with pytest.raises(ReportValidationError, match="change_type"):
        validate_report(report)
    report = build_report(DOC, OLD_V, NEW_V, OLD_TEXT, NEW_TEXT)
    report["claims"][0]["citation_ids"].append("c999")
    with pytest.raises(ReportValidationError, match="unknown citation"):
        validate_report(report)


def test_schema_rejects_malformed_model_output():
    with pytest.raises(ReportValidationError):
        validate_report({"summary": "not a report"})
    with pytest.raises(ReportValidationError):
        validate_report({"document_title": "x"})
