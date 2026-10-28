"""M10 backup unit tests: create, verify, restore, retention."""
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lawradar.db import backup, store
from lawradar.db.lock import LockBusy, exclusive_lock, runtime_lock


def _seed(db_path) -> None:
    store.init_db(db_path)
    conn = store.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sources (id, name, base_url, access_method, enabled, "
            "terms_review_status) VALUES ('fx','FX','https://example.invalid',"
            "'fixture',1,'reviewed_ok')")
        conn.execute(
            "INSERT INTO documents (source_id, source_document_id, title) "
            "VALUES ('fx','doc-1','Example Act')")
        doc_id = conn.execute("SELECT id FROM documents").fetchone()[0]
        conn.execute(
            "INSERT INTO document_versions (document_id, version_number, "
            "content_sha256, extraction_status) VALUES (?,1,?, 'extracted')",
            (doc_id, "a" * 64))
        version_id = conn.execute(
            "SELECT id FROM document_versions").fetchone()[0]
        conn.execute(
            "INSERT INTO change_reports (document_id, new_version_id, "
            "change_type, summary, published_at) VALUES (?,?,'amendment',"
            "'A claim','2026-10-26T00:00:00.000Z')", (doc_id, version_id))
        report_id = conn.execute("SELECT id FROM change_reports").fetchone()[0]
        conn.execute(
            "INSERT INTO citations (change_report_id, document_version_id, "
            "locator_type, locator_value, quoted_text) VALUES (?,?,'text span',"
            "'section 1','text')", (report_id, version_id))
        conn.execute(
            "INSERT INTO ingestion_runs (source_id, status) VALUES ('fx','ok')")
        conn.execute(
            "INSERT INTO review_tasks (change_report_id, reason) "
            "VALUES (?,'check status')", (report_id,))
        conn.commit()
    finally:
        conn.close()


def _counts(db_path, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_create_writes_verified_snapshot_and_manifest(tmp_path):
    db = tmp_path / "lawradar.db"
    _seed(db)
    info = backup.create_backup(db, tmp_path / "out")
    path = Path(info.path)
    assert path.is_file()
    assert path.with_name(path.name + ".sha256").is_file()
    manifest = json.loads(
        path.with_name(path.name + ".json").read_text(encoding="utf-8"))
    assert manifest["format"] == 1
    assert manifest["sha256"] == info.sha256 == backup.sha256_file(path)
    assert manifest["counts"] == info.counts
    assert info.counts == {
        "sources": 1, "documents": 1, "versions": 1, "reports": 1,
        "published_reports": 1, "citations": 1, "review_tasks": 1, "runs": 1,
    }
    assert len(info.migrations) == 5
    verified = backup.verify_backup(path)
    assert verified.sha256 == info.sha256
    assert verified.counts == info.counts
    assert verified.has_manifest is True


def test_verify_fails_closed_on_tamper_missing_sidecar_and_manifest(tmp_path):
    db = tmp_path / "lawradar.db"
    _seed(db)
    info = backup.create_backup(db, tmp_path / "out")
    path = Path(info.path)

    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(backup.BackupError, match="checksum mismatch"):
        backup.verify_backup(path)

    clean = backup.create_backup(db, tmp_path / "out2")
    clean_path = Path(clean.path)
    clean_path.with_name(clean_path.name + ".sha256").unlink()
    with pytest.raises(backup.BackupError, match="sidecar missing"):
        backup.verify_backup(clean_path)

    manifest_path = clean_path.with_name(clean_path.name + ".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["reports"] = 99
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    clean_path.with_name(clean_path.name + ".sha256").write_text(
        f"{clean.sha256}  {clean.name}\n", encoding="ascii")
    with pytest.raises(backup.BackupError, match="manifest counts"):
        backup.verify_backup(clean_path)


def test_verify_requires_manifest_sidecar(tmp_path):
    db = tmp_path / "lawradar.db"
    _seed(db)
    info = backup.create_backup(db, tmp_path / "out")
    path = Path(info.path)
    path.with_name(path.name + ".json").unlink()
    with pytest.raises(backup.BackupError, match="manifest sidecar missing"):
        backup.verify_backup(path)


def test_restore_requires_force_and_keeps_safety_snapshot(tmp_path):
    db = tmp_path / "lawradar.db"
    _seed(db)
    info = backup.create_backup(db, tmp_path / "out")
    conn = store.connect(db)
    try:
        conn.execute("DELETE FROM review_tasks")
        conn.execute("DELETE FROM change_reports")
        conn.commit()
    finally:
        conn.close()
    assert _counts(db, "change_reports") == 0
    stale_journal = db.with_name(db.name + "-journal")
    stale_journal.write_bytes(b"stale")

    with pytest.raises(backup.BackupError, match="--force"):
        backup.restore_backup(info.path, db)

    result = backup.restore_backup(
        info.path, db, force=True, safety_dir=tmp_path / "safety")
    assert result["safety_backup"]
    safety = Path(result["safety_backup"])
    assert safety.is_file()
    assert _counts(safety, "change_reports") == 0
    assert _counts(db, "change_reports") == 1
    assert not stale_journal.exists()
    assert result["counts"]["published_reports"] == 1
    assert backup.verify_backup(info.path).sha256 == info.sha256


def test_restore_rechecks_copied_bytes_after_verify(tmp_path, monkeypatch):
    db = tmp_path / "lawradar.db"
    _seed(db)
    first = backup.create_backup(db, tmp_path / "out")
    conn = store.connect(db)
    try:
        conn.execute("DELETE FROM review_tasks")
        conn.execute("DELETE FROM change_reports")
        conn.commit()
    finally:
        conn.close()
    second = backup.create_backup(db, tmp_path / "out")
    assert first.sha256 != second.sha256

    monkeypatch.setattr(backup, "verify_backup", lambda _path: first)
    with pytest.raises(backup.BackupError, match="restored copy checksum"):
        backup.restore_backup(second.path, db, force=True)
    assert _counts(db, "change_reports") == 0


def test_runtime_locks_coexist_but_block_exclusive_restore(tmp_path):
    db = tmp_path / "lawradar.db"
    with runtime_lock(db):
        with runtime_lock(db):
            with pytest.raises(LockBusy):
                with exclusive_lock(db):
                    pass


def test_restore_fails_closed_while_database_is_in_use(tmp_path):
    db = tmp_path / "lawradar.db"
    _seed(db)
    info = backup.create_backup(db, tmp_path / "out")
    with runtime_lock(db):
        with pytest.raises(backup.BackupError, match="in use"):
            backup.restore_backup(info.path, db, force=True)
    assert _counts(db, "change_reports") == 1


def test_restore_preserves_unreadable_target_as_unverified_copy(tmp_path):
    db = tmp_path / "lawradar.db"
    _seed(db)
    info = backup.create_backup(db, tmp_path / "out")
    db.write_bytes(b"not a sqlite database")

    result = backup.restore_backup(
        info.path, db, force=True, safety_dir=tmp_path / "safety")
    safety = Path(result["safety_backup"])
    assert "pre-restore-unverified" in safety.name
    assert safety.read_bytes() == b"not a sqlite database"
    assert _counts(db, "change_reports") == 1
    assert backup.verify_backup(info.path).sha256 == info.sha256


def test_retention_only_prunes_matching_backups(tmp_path):
    db = tmp_path / "lawradar.db"
    _seed(db)
    out = tmp_path / "out"
    start = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
    first = backup.create_backup(db, out, now=start)
    second = backup.create_backup(
        db, out, now=start + timedelta(seconds=1))
    unrelated = out / "lawradar-notes.db"
    unrelated.write_bytes(b"keep me")
    third = backup.create_backup(
        db, out, now=start + timedelta(seconds=2), keep=2)
    assert not Path(first.path).exists()
    assert not Path(first.path + ".sha256").exists()
    assert not Path(first.path + ".json").exists()
    assert Path(second.path).exists()
    assert Path(second.path + ".sha256").exists()
    assert Path(third.path).exists()
    assert unrelated.read_bytes() == b"keep me"


def test_retention_never_deletes_the_new_backup_on_clock_skew(tmp_path):
    db = tmp_path / "lawradar.db"
    _seed(db)
    out = tmp_path / "out"
    start = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)
    first = backup.create_backup(db, out, now=start)
    second = backup.create_backup(
        db, out, now=start - timedelta(hours=1), keep=1)
    assert Path(second.path).exists()
    assert not Path(first.path).exists()
