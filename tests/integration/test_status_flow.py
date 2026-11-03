"""M14 acceptance: operator status via CLI and the JSON API."""
import json
import threading
import urllib.request

import pytest
import yaml

from lawradar.cli import main
from lawradar.config import load_settings
from lawradar.db import store
from lawradar.web.server import build_server

V1 = (b"<html><body><h1>Status Act</h1><h2>Section 1 - Scope</h2>"
      b"<p>A sufficiently long status paragraph for the flow test.</p>"
      b"</body></html>")

MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "terms_review_status": "not_reviewed",
    "enabled": True, "rate_limit_seconds": 0,
}


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [MANUAL]}), encoding="utf-8")
    target = tmp_path / "s.html"
    target.write_bytes(V1)
    assert main(["--data-dir", config.data_dir, "ingest", "m",
                 "--sources-file", str(sources), "--file", str(target),
                 "--title", "Status Act", "--doc-id", "status"]) == 0
    yield config, tmp_path


def test_status_cli_text_and_json(setup, capsys):
    config, _ = setup
    assert main(["--data-dir", config.data_dir, "status"]) == 0
    out = capsys.readouterr().out
    assert "India Law Radar v" in out
    assert "documents: 1 (1 versions)" in out
    assert "last run:" in out
    assert "attention:" in out

    capsys.readouterr()
    assert main(["--data-dir", config.data_dir, "--json", "status"]) == 0
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["app"]["migrations"] == 8
    assert snapshot["documents"]["documents"] == 1
    assert snapshot["reports"]["total"] >= 1
    assert "attention" in snapshot


def test_status_without_database_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    assert main(["--data-dir", str(tmp_path / "empty"), "status"]) == 1
    assert "no database yet" in capsys.readouterr().err


def test_api_status_endpoint(setup):
    _, tmp_path = setup
    server = build_server(
        str(tmp_path / "data" / "lawradar.db"),
        host="127.0.0.1", port=0, token="")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(base + "/api/status", timeout=10) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["app"]["migrations"] == 8
        assert payload["documents"]["documents"] == 1
        assert isinstance(payload["attention"], list)
        conn = store.connect(tmp_path / "data" / "lawradar.db")
        try:
            assert payload["reports"]["total"] == store.count_reports(conn)
        finally:
            conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
