"""M2 acceptance flow: idempotent ingest, new version on change, failed runs.

- Same bytes twice -> no duplicate version.
- Changed bytes, same document -> new version.
- Failed fetch -> run failed, source NOT marked successfully checked.
- Manual import round-trips through the CLI path.
"""
import sqlite3

import pytest
import yaml

from lawradar.cli import main
from lawradar.config import load_settings
from lawradar.db import store
from lawradar.ingestion.pipeline import ingest_bytes, run_ingestion

DOC = {
    "source_id": "manual-sample",
    "source_document_id": "act-1",
    "title": "Test Act",
    "issuing_authority": "Test Authority",
    "jurisdiction": "central",
    "official_url": "https://www.indiacode.nic.in/test",
}
V1 = b"<html><body><h1>Test Act</h1><p>File within thirty days.</p></body></html>"
V2 = (b"<html><body><h1>Test Act</h1><p>File within forty-five days.</p>"
      b"<p>Late fee applies.</p></body></html>")


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    db_path = tmp_path / "data" / "lawradar.db"
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{db_path}"
    store.init_db(db_path)
    conn = store.connect(db_path)
    from lawradar.sources.registry import SourceRecord
    store.upsert_source(conn, SourceRecord(
        id="manual-sample", name="Manual", base_url="https://www.indiacode.nic.in/",
        access_method="manual_import", enabled=True))
    conn.commit()
    yield config, conn
    conn.close()


def _sources_yaml(tmp_path, entries):
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump({"sources": entries}), encoding="utf-8")
    return str(path)


def test_same_bytes_twice_no_duplicate(isolated):
    config, conn = isolated
    first = ingest_bytes(conn, raw_bytes=V1, content_type="text/html",
                         filename="a.html", data_dir=config.data_dir, **DOC)
    conn.commit()
    assert first.status == "new_document"
    second = ingest_bytes(conn, raw_bytes=V1, content_type="text/html",
                          filename="a.html", data_dir=config.data_dir, **DOC)
    assert second.status == "duplicate"
    assert second.version_id == first.version_id
    assert store.count_versions(conn, first.document_id) == 1


def test_changed_bytes_create_new_version(isolated):
    config, conn = isolated
    first = ingest_bytes(conn, raw_bytes=V1, content_type="text/html",
                         filename="a.html", data_dir=config.data_dir, **DOC)
    conn.commit()
    changed = ingest_bytes(conn, raw_bytes=V2, content_type="text/html",
                           filename="a.html", data_dir=config.data_dir, **DOC)
    conn.commit()
    assert changed.status == "new_version"
    assert changed.version_number == first.version_number + 1
    assert store.count_versions(conn, first.document_id) == 2


def test_empty_bytes_rejected(isolated):
    _, conn = isolated
    with pytest.raises(ValueError, match="empty"):
        ingest_bytes(conn, raw_bytes=b"", data_dir="data", **DOC)


def test_metadata_change_same_bytes_no_new_version(isolated):
    config, conn = isolated
    first = ingest_bytes(conn, raw_bytes=V1, content_type="text/html",
                         filename="a.html", data_dir=config.data_dir, **DOC)
    conn.commit()
    renamed = ingest_bytes(conn, raw_bytes=V1, content_type="text/html",
                           filename="a.html", data_dir=config.data_dir,
                           **{**DOC, "title": "Test Act (renamed)"})
    assert renamed.status == "duplicate"
    assert store.count_versions(conn, first.document_id) == 1


def test_restricted_storage_skips_raw_bytes(isolated):
    config, conn = isolated
    result = ingest_bytes(conn, raw_bytes=V1, content_type="text/html",
                          filename="a.html", storage_policy="restricted",
                          data_dir=config.data_dir, **DOC)
    assert result.status == "new_document"
    row = store.latest_version(conn, result.document_id)
    assert row["raw_storage_path"] is None
    assert any("restricted" in w for w in result.warnings)


def test_failed_http_run_does_not_mark_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    sources = _sources_yaml(tmp_path, [{
        "id": "dead-probe", "name": "Dead probe",
        "base_url": "http://127.0.0.1:9/unreachable",
        "access_method": "http_poll", "terms_review_status": "not_reviewed",
        "enabled": True, "rate_limit_seconds": 0,
    }])
    summary = run_ingestion(config, sources, source_id="dead-probe")
    assert summary["runs"][0]["status"] == "failed"
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    try:
        source = store.get_source(conn, "dead-probe")
        assert not source["last_success_at"]  # never marked successfully checked
        assert source["last_error"]
        runs = store.latest_runs(conn, 1)
        assert runs[0]["status"] == "failed"
    finally:
        conn.close()


def test_fixture_ingest_twice_via_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    data = tmp_path / "data"
    sources = _sources_yaml(tmp_path, [{
        "id": "fixture-sample", "name": "Fixture",
        "base_url": "https://example.invalid/fixture/",
        "access_method": "fixture", "terms_review_status": "reviewed_ok",
        "enabled": True, "rate_limit_seconds": 0,
    }])
    args = ["--data-dir", str(data), "ingest", "fixture-sample",
            "--sources-file", sources]
    assert main(args) == 0
    capsys.readouterr()
    assert main(args) == 0  # second run: all duplicates
    out = capsys.readouterr().out
    assert "changed=0" in out
    db = sqlite3.connect(data / "lawradar.db")
    try:
        count = db.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0]
        assert count == 2  # two fixture docs, one version each
    finally:
        db.close()
