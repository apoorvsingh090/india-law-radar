"""Review queue tests: decisions, notes enforcement, publication gating."""
import pytest

from lawradar.db import store
from lawradar.review.queue import (ReviewError, audit_trail, auto_queue,
                                   queue_summary, resolve)


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
        conn, source_id="s", source_document_id="d", title="T")
    ver = store.create_version(
        conn, document_id=doc, content_sha256="x" * 64,
        raw_storage_path=None, extracted_text_path=None,
        extraction_method="html", extraction_status="ok",
        parser_warnings=[], review_status="pending")
    rep = store.create_report(
        conn, document_id=doc, old_version_id=None, new_version_id=ver,
        change_type="text_modified", summary="S", claims=[])
    conn.commit()
    yield conn, doc, ver, rep
    conn.close()


def test_auto_queue_only_uncertain(db):
    conn, _, ver, rep = db
    assert auto_queue(conn, report_id=rep, change_type="text_modified",
                      new_version_id=ver, extraction_status="ok") == []
    task = auto_queue(conn, report_id=rep, change_type="unknown",
                      new_version_id=ver, extraction_status="failed")
    assert len(task) == 1
    # Idempotent: same reason twice opens nothing new.
    assert auto_queue(conn, report_id=rep, change_type="unknown",
                      new_version_id=ver, extraction_status="failed") == task


def test_approve_publishes(db):
    conn, _, _, rep = db
    out = resolve(conn, report_id=rep, decision="approved",
                  reviewer="A. Reviewer", notes="checked against source")
    assert out["verification"] == "approved"
    row = store.get_report(conn, rep)
    assert row["verification_status"] == "approved"
    assert row["published_at"]  # safe publication: only via approval
    trail = audit_trail(conn, rep)
    assert len(trail) == 1 and trail[0]["reviewer"] == "A. Reviewer"


def test_reject_requires_notes(db):
    conn, _, _, rep = db
    with pytest.raises(ReviewError, match="notes are required"):
        resolve(conn, report_id=rep, decision="rejected", notes="  ")
    with pytest.raises(ReviewError, match="notes are required"):
        resolve(conn, report_id=rep, decision="needs_changes")
    out = resolve(conn, report_id=rep, decision="rejected",
                  notes="not a real change")
    assert out["verification"] == "rejected"
    row = store.get_report(conn, rep)
    assert not row["published_at"]  # rejected reports never publish


def test_unknown_decision_and_report_rejected(db):
    conn, _, _, rep = db
    with pytest.raises(ReviewError, match="unknown decision"):
        resolve(conn, report_id=rep, decision="maybe")
    with pytest.raises(ReviewError, match="unknown report"):
        resolve(conn, report_id=999, decision="approved")


def test_queue_summary_counts(db):
    conn, _, ver, rep = db
    auto_queue(conn, report_id=rep, change_type="corrigendum",
               new_version_id=ver, extraction_status="ok")
    summary = queue_summary(conn)
    assert summary["pending"] == 1 and summary["total"] == 1
