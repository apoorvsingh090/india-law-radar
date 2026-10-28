"""M10 acceptance: create -> verify -> restore through the real CLI."""
import json
from pathlib import Path

import pytest
import yaml

from lawradar.cli import main
from lawradar.db import store

FIXTURE = {
    "id": "fx", "name": "FX", "base_url": "https://example.invalid/fx/",
    "access_method": "fixture", "enabled": True, "rate_limit_seconds": 0,
    "poll_interval_minutes": 1440, "storage_policy": "allowed",
    "terms_review_status": "reviewed_ok",
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [FIXTURE]}),
                       encoding="utf-8")
    data = tmp_path / "data"
    assert main(["--data-dir", str(data), "ingest", "fx",
                 "--sources-file", str(sources)]) == 0
    return data, sources, data / "lawradar.db"


def _run(data, capsys, argv, *, as_json=False):
    args = ["--data-dir", str(data)]
    if as_json:
        args.append("--json")
    args += argv
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _count(db, sql):
    conn = store.connect(db)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def test_cli_backup_verify_restore_round_trip(env, capsys):
    data, _, db = env
    reports = _count(db, "SELECT COUNT(*) FROM change_reports")
    assert reports >= 1

    code, out, err = _run(
        data, capsys, ["backup", "create"], as_json=True)
    assert code == 0, err
    created = json.loads(out)
    path = Path(created["path"])
    assert path.is_file()
    assert created["counts"]["reports"] == reports
    assert path.with_name(path.name + ".json").is_file()

    code, out, err = _run(
        data, capsys, ["backup", "verify", str(path)], as_json=True)
    assert code == 0, err
    verified = json.loads(out)
    assert verified["sha256"] == created["sha256"]
    assert verified["has_manifest"] is True

    conn = store.connect(db)
    try:
        conn.execute("DELETE FROM review_tasks")
        conn.execute("DELETE FROM change_reports")
        conn.commit()
    finally:
        conn.close()
    assert _count(db, "SELECT COUNT(*) FROM change_reports") == 0

    code, _, err = _run(data, capsys, ["backup", "restore", str(path)])
    assert code == 1
    assert "without --force" in err
    assert _count(db, "SELECT COUNT(*) FROM change_reports") == 0

    code, out, err = _run(
        data, capsys, ["backup", "restore", str(path), "--force"],
        as_json=True)
    assert code == 0, err
    restored = json.loads(out)
    assert restored["counts"]["reports"] == reports
    assert restored["safety_backup"]
    safety = Path(restored["safety_backup"])
    assert safety.is_file()
    assert _count(safety, "SELECT COUNT(*) FROM change_reports") == 0
    assert _count(db, "SELECT COUNT(*) FROM change_reports") == reports

    code, _, err = _run(data, capsys, ["backup", "verify", str(path)])
    assert code == 0, err


def test_cli_rejects_tampered_backup(env, capsys):
    data, _, _ = env
    code, out, _ = _run(
        data, capsys, ["backup", "create"], as_json=True)
    assert code == 0
    path = Path(json.loads(out)["path"])
    path.write_bytes(path.read_bytes() + b"tampered")

    code, _, err = _run(data, capsys, ["backup", "verify", str(path)])
    assert code == 1
    assert "checksum mismatch" in err
