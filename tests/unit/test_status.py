"""Operator status snapshot tests (Milestone 14): local-state only."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from lawradar.db import store
from lawradar.status import collect_status, format_status

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)


def _ts(minutes_ago: float) -> str:
    moment = NOW - timedelta(minutes=minutes_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _config(tmp_path, *, notify_enabled=False, webhooks=None):
    return SimpleNamespace(
        db_url=f"sqlite:///{tmp_path / 't.db'}",
        data_dir=str(tmp_path),
        notify_enabled=notify_enabled,
        notify_webhooks=webhooks or [],
    )


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "t.db"
    store.init_db(path)
    conn = store.connect(path)
    yield conn, tmp_path
    conn.close()


def _seed_report(conn, *, approved: bool = False) -> int:
    from lawradar.sources.registry import SourceRecord

    seed = store.count_reports(conn) + 1
    store.upsert_source(conn, SourceRecord(
        id="s", name="S", base_url="https://example.invalid/",
        access_method="manual_import", enabled=True))
    doc = store.get_or_create_document(
        conn, source_id="s", source_document_id=f"d{seed}", title="T")
    ver = store.create_version(
        conn, document_id=doc, content_sha256=f"{seed:064d}",
        raw_storage_path=None, extracted_text_path=None,
        extraction_method="html", extraction_status="ok",
        parser_warnings=[], review_status="pending")
    report = store.create_report(
        conn, document_id=doc, old_version_id=None, new_version_id=ver,
        change_type="text_modified", summary="S", claims=[])
    task = store.create_review_task(
        conn, document_version_id=ver, change_report_id=report,
        reason="test")
    conn.commit()
    if approved:
        store.resolve_review_task(
            conn, task, status="approved", reviewer="tester",
            review_notes="ok")
        store.publish_report(conn, report, reviewer_notes="ok")
        conn.commit()
    return report


def test_empty_database_snapshot(db):
    conn, tmp_path = db
    snapshot = collect_status(conn, _config(tmp_path), now=NOW)
    assert snapshot["generated_at"] == "2026-11-03T12:00:00Z"
    assert snapshot["sources"]["monitored"] == 0
    assert snapshot["documents"] == {"documents": 0, "versions": 0}
    assert snapshot["reports"]["total"] == 0
    assert snapshot["reports"]["pending_review"] == 0
    assert snapshot["notifications"] == {
        "enabled": False, "targets": 0, "failed_attempts": 0}
    assert snapshot["backup"] is None
    assert snapshot["last_run"] is None
    assert snapshot["attention"] == []
    assert snapshot["app"]["migrations"] == 8
    assert snapshot["app"]["pending_migrations"] == []


def test_pending_migration_flagged(db):
    conn, tmp_path = db
    conn.execute(
        "DELETE FROM _migrations WHERE name='008_http_validators.sql'")
    conn.commit()
    snapshot = collect_status(conn, _config(tmp_path), now=NOW)
    assert snapshot["app"]["pending_migrations"] == ["008_http_validators.sql"]
    assert any("schema is behind" in item for item in snapshot["attention"])


def test_pending_review_and_unexported_approved_flagged(db):
    conn, tmp_path = db
    _seed_report(conn)                     # pending review
    _seed_report(conn, approved=True)      # approved, no bundle
    snapshot = collect_status(conn, _config(tmp_path), now=NOW)
    assert snapshot["reports"]["total"] == 2
    assert snapshot["reports"]["pending_review"] == 1
    assert snapshot["reports"]["approved"] == 1
    assert snapshot["reports"]["approved_without_bundle"] == 1
    joined = " | ".join(snapshot["attention"])
    assert "awaiting review" in joined
    assert "no evidence bundle" in joined


def test_exported_approved_report_not_flagged(db):
    conn, tmp_path = db
    report = _seed_report(conn, approved=True)
    store.record_evidence_bundle(
        conn, change_report_id=report, path="x.zip", name="x.zip",
        sha256="a" * 64, bytes=10, has_document=False)
    conn.commit()
    snapshot = collect_status(conn, _config(tmp_path), now=NOW)
    assert snapshot["reports"]["approved_without_bundle"] == 0
    assert not any("evidence bundle" in item for item in snapshot["attention"])


def test_failing_source_and_webhook_attention(db):
    conn, tmp_path = db
    from lawradar.sources.registry import SourceRecord

    store.upsert_source(conn, SourceRecord(
        id="poll", name="Poll", base_url="https://example.invalid/",
        access_method="http_poll", enabled=True, poll_interval_minutes=60))
    store.record_source_check(conn, "poll", False, "connect timeout")
    report = _seed_report(conn, approved=True)
    store.record_notification_attempt(
        conn, change_report_id=report, webhook="hook",
        url="https://example.invalid/hook", status="failed",
        error="HTTP 500")
    conn.commit()
    snapshot = collect_status(
        conn, _config(tmp_path, notify_enabled=True,
                      webhooks=[{"name": "hook"}]),
        now=NOW)
    assert snapshot["sources"]["failing"] == 1
    assert snapshot["notifications"]["enabled"] is True
    assert snapshot["notifications"]["targets"] == 1
    assert snapshot["notifications"]["failed_attempts"] == 1
    joined = " | ".join(snapshot["attention"])
    assert "is failing" in joined
    assert "notify send" in joined


def test_latest_backup_reported(db):
    conn, tmp_path = db
    backups = tmp_path / "backups"
    backups.mkdir()
    db_file = backups / "lawradar-2026.db"
    db_file.write_bytes(b"x" * 32)
    snapshot = collect_status(conn, _config(tmp_path), now=NOW)
    assert snapshot["backup"]["name"] == "lawradar-2026.db"
    assert snapshot["backup"]["bytes"] == 32
    assert snapshot["backup"]["verified_sidecar"] is False


def test_format_status_is_stable_text(db):
    conn, tmp_path = db
    _seed_report(conn)
    text = format_status(collect_status(conn, _config(tmp_path), now=NOW))
    assert "India Law Radar v" in text
    assert "sources: 0 monitored" in text
    assert "reports: 1 total" in text
    assert "attention:" in text
    assert "awaiting review" in text
