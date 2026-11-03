"""Markdown brief tests (Milestone 15): approved-only, deterministic."""
import pytest

from lawradar.db import store
from lawradar.reporting.brief import (
    BriefError,
    BriefRefused,
    build_brief,
)
from lawradar.review.queue import resolve

GEN_AT = "2026-11-03T12:00:00Z"


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "t.db"
    store.init_db(path)
    conn = store.connect(path)
    from lawradar.sources.registry import SourceRecord

    store.upsert_source(conn, SourceRecord(
        id="s", name="S", base_url="https://example.invalid/",
        access_method="manual_import", enabled=True))
    doc = store.get_or_create_document(
        conn, source_id="s", source_document_id="d",
        title="The Sample Act 2026")
    conn.commit()
    ver = store.create_version(
        conn, document_id=doc, content_sha256="a" * 64,
        raw_storage_path=None, extracted_text_path=None,
        extraction_method="html", extraction_status="ok",
        parser_warnings=[], review_status="pending")
    report = store.create_report(
        conn, document_id=doc, old_version_id=None, new_version_id=ver,
        change_type="new_document",
        summary="First captured version of the Sample Act.",
        claims=[{"claim": "The document is stored.",
                 "claim_type": "source_fact",
                 "citation_ids": ["c1"],
                 "verification_status": "unverified"}])
    store.add_citation(
        conn, change_report_id=report, document_version_id=ver,
        locator_type="URL", locator_value="https://example.invalid/d",
        quoted_text="The Sample Act 2026",
        source_url="https://example.invalid/d")
    conn.commit()
    yield conn, doc, ver, report
    conn.close()


def _approve(conn, report: int) -> None:
    resolve(conn, report_id=report, decision="approved", reviewer="reviewer",
            notes="Checked against the official page.")
    conn.commit()


def test_draft_is_refused(db):
    conn, _, _, report = db
    with pytest.raises(BriefRefused, match="not approved"):
        build_brief(conn, report, generated_at=GEN_AT)


def test_unknown_report_is_error(db):
    conn, _, _, _ = db
    with pytest.raises(BriefError, match="unknown report"):
        build_brief(conn, 999, generated_at=GEN_AT)


def test_approved_brief_contains_evidence(db):
    conn, _, _, report = db
    _approve(conn, report)
    text = build_brief(conn, report, generated_at=GEN_AT)
    assert text.startswith("# The Sample Act 2026")
    assert f"**Change report #{report}**" in text
    assert "**Status:** approved" in text
    assert "First captured version of the Sample Act." in text
    assert "sha256 `aaaaaaaaaaaaaaaa`" in text
    assert "## Claims" in text
    assert "citations: c1" in text
    assert "https://example.invalid/d" in text
    assert "reviewer approved" in text
    assert "Checked against the official page." in text
    assert "lawradar reports verify" in text
    assert "not legal advice" in text
    # Deterministic for the same inputs.
    again = build_brief(conn, report, generated_at=GEN_AT)
    assert text == again


def test_brief_without_previous_version_is_explicit(db):
    conn, _, _, report = db
    _approve(conn, report)
    text = build_brief(conn, report, generated_at=GEN_AT)
    assert "Previous version: none (first captured version)" in text
