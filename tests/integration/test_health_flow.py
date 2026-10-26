"""M9 acceptance: health CLI + web/API surface reflect real sweep state."""
import json
import threading
import time
import urllib.request

import pytest
import yaml

from lawradar.cli import main
from lawradar.config import load_settings
from lawradar.db import store
from lawradar.web.server import build_server

FIXTURE = {
    "id": "fx", "name": "FX", "base_url": "https://example.invalid/fx/",
    "access_method": "fixture", "enabled": True, "rate_limit_seconds": 0,
    "poll_interval_minutes": 1440, "storage_policy": "allowed",
    "terms_review_status": "reviewed_ok",
}
MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "enabled": True,
    "rate_limit_seconds": 0, "poll_interval_minutes": 10080,
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump({"sources": [FIXTURE, MANUAL]}),
                    encoding="utf-8")
    return config, str(path), tmp_path / "data" / "lawradar.db"


def _health(config, sources_file, capsys, *, as_json=False):
    argv = ["--data-dir", config.data_dir]
    if as_json:
        argv.append("--json")
    argv += ["sources", "health", "--sources-file", sources_file]
    code = main(argv)
    out = capsys.readouterr().out
    return code, (json.loads(out) if as_json else out)


def test_health_tracks_sweep_staleness_and_failure(env, capsys):
    config, sources_file, db_path = env
    assert main(["--data-dir", config.data_dir, "watch", "--once",
                 "--sources-file", sources_file]) == 0
    capsys.readouterr()

    code, out = _health(config, sources_file, capsys)
    assert code == 0
    assert "fx: ok" in out and "m: manual" in out
    assert "health: OK (1 monitored, 0 stale, 0 failing)" in out

    code, payload = _health(config, sources_file, capsys, as_json=True)
    assert code == 0 and payload["healthy"] is True
    assert payload["monitored"] == 1 and payload["unhealthy"] == 0
    by_id = {s["source_id"]: s for s in payload["sources"]}
    assert by_id["fx"]["next_due_at"].endswith("Z")
    assert by_id["m"]["monitored"] is False

    # Age the last success beyond 2x the poll interval: stale, exit 1.
    conn = store.connect(db_path)
    try:
        conn.execute(
            "UPDATE sources SET last_checked_at='2000-01-01T00:00:00.000Z', "
            "last_success_at='2000-01-01T00:00:00.000Z' WHERE id='fx'")
        conn.commit()
    finally:
        conn.close()
    code, out = _health(config, sources_file, capsys)
    assert code == 1
    assert "fx: stale" in out and "health: FAILED" in out

    # A recorded error wins over any timestamp: failing.
    conn = store.connect(db_path)
    try:
        conn.execute(
            "UPDATE sources SET last_error='HTTP 503 from source' "
            "WHERE id='fx'")
        conn.commit()
    finally:
        conn.close()
    code, payload = _health(config, sources_file, capsys, as_json=True)
    assert code == 1
    assert payload["failing"] == 1
    fx = next(s for s in payload["sources"] if s["source_id"] == "fx")
    assert fx["status"] == "failing"
    assert "HTTP 503" in fx["detail"]


def test_sources_page_and_api_expose_health(env, capsys):
    config, sources_file, db_path = env
    assert main(["--data-dir", config.data_dir, "watch", "--once",
                 "--sources-file", sources_file]) == 0
    capsys.readouterr()
    conn = store.connect(db_path)
    try:
        conn.execute(
            "UPDATE sources SET last_checked_at='2000-01-01T00:00:00.000Z', "
            "last_success_at='2000-01-01T00:00:00.000Z' WHERE id='fx'")
        conn.commit()
    finally:
        conn.close()

    server = build_server(str(db_path), host="127.0.0.1", port=0, token="")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(100):
        if server.server_address[1]:
            break
        time.sleep(0.05)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/sources/health",
                                    timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["healthy"] is False
        assert payload["stale"] == 1
        fx = next(s for s in payload["sources"] if s["source_id"] == "fx")
        assert fx["status"] == "stale"
        with urllib.request.urlopen(base + "/sources", timeout=10) as resp:
            page = resp.read().decode("utf-8")
        assert "stale" in page and "badge bad" in page
        assert "Next due" in page
    finally:
        server.shutdown()
        thread.join(timeout=5)
