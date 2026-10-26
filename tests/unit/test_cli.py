"""CLI tests (Milestone 2): all commands functional, no placeholders."""
import json
import sqlite3

from lawradar.cli import build_parser, main


def test_health_passes_in_isolated_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    rc = main(["--data-dir", str(tmp_path / "data"), "health"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "health" in out.lower()


def test_health_json_shape(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LAWRADAR_CONFIG", raising=False)
    rc = main(["--data-dir", str(tmp_path / "d"), "--json", "health"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert {"config_loads", "data_dir_writable", "sqlite"} <= set(payload["checks"])


def test_init_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LAWRADAR_CONFIG", raising=False)
    data = tmp_path / "data"
    assert main(["--data-dir", str(data), "init"]) == 0
    assert main(["--data-dir", str(data), "init"]) == 0  # second run must pass
    db = data / "lawradar.db"
    assert db.is_file()
    conn = sqlite3.connect(db)
    try:
        migrations = {r[0] for r in conn.execute("SELECT name FROM _migrations")}
        assert "001_init.sql" in migrations
        tables = {r[0] for r in
                  conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"sources", "documents", "document_versions",
                "ingestion_runs"} <= tables
    finally:
        conn.close()


def test_parser_has_only_implemented_commands():
    parser = build_parser()
    actions = [a for a in parser._subparsers._group_actions]
    commands = set(actions[0].choices) if actions else set()
    assert commands == {"init", "health", "sources", "ingest", "watch",
                        "documents", "reports", "review", "serve", "eval",
                        "feedback"}


def test_sources_list_runs_in_isolated_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    data = tmp_path / "data"
    assert main(["--data-dir", str(data), "init"]) == 0
    capsys.readouterr()
    # No sources.yaml in tmp dir and none shipped here -> registry empty,
    # but the command itself must work, not crash.
    assert main(["--data-dir", str(data), "sources", "list"]) == 0
