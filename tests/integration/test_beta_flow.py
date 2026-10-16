"""M7 acceptance: beta pages, feedback loop, rate limits, headers."""
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
import yaml

from lawradar.cli import main
from lawradar.config import load_settings
from lawradar.db import store
from lawradar.web.server import build_server

V1 = (b"<html><body><h1>Beta Act</h1><h2>Section 1 - Scope</h2>"
      b"<p>A sufficiently long beta paragraph for the flow test.</p>"
      b"</body></html>")

MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "terms_review_status": "not_reviewed",
    "enabled": True, "rate_limit_seconds": 0,
}


@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [MANUAL]}), encoding="utf-8")
    target = tmp_path / "b.html"
    target.write_bytes(V1)
    assert main(["--data-dir", config.data_dir, "ingest", "m",
                 "--sources-file", str(sources), "--file", str(target),
                 "--title", "Beta Act", "--doc-id", "beta"]) == 0
    server = build_server(str(tmp_path / "data" / "lawradar.db"),
                          host="127.0.0.1", port=0, token="",
                          post_limit_per_minute=3)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(100):
        if server.server_address[1]:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    server.shutdown()
    thread.join(timeout=5)


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode("utf-8",
                                                               "replace")


def _post(base, path, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(base + path, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def test_beta_pages(live):
    base, _ = live
    for path, marker in [("/privacy", "No accounts"),
                         ("/limitations", "not complete"),
                         ("/feedback", "What is wrong")]:
        status, _, body = _get(base, path)
        assert status == 200, path
        assert marker in body, path
    _, _, home = _get(base, "/")
    assert 'href="/limitations"' in home and 'href="/feedback"' in home


def test_security_headers_present(live):
    base, _ = live
    _, headers, _ = _get(base, "/")
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"


def test_feedback_loop_creates_task(live):
    base, tmp_path = live
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    rid = store.list_reports(conn)[0]["id"]
    conn.close()
    status, _ = _post(base, "/feedback",
                      {"report_id": str(rid), "message": "Title looks wrong"})
    assert status == 200
    status, _ = _post(base, "/feedback", {"message": "  "})
    assert status == 400
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    try:
        rows = store.list_feedback(conn)
        assert len(rows) == 1 and rows[0]["change_report_id"] == rid
        tasks = [t for t in store.list_review_tasks(conn, status="pending")
                 if t["change_report_id"] == rid]
        assert any("user-reported error" in t["reason"] for t in tasks)
    finally:
        conn.close()


def test_post_rate_limit(live):
    base, tmp_path = live
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    rid = store.list_reports(conn)[0]["id"]
    conn.close()
    codes = [_post(base, "/feedback",
                   {"report_id": str(rid), "message": f"spam {i}"})[0]
             for i in range(5)]
    assert 429 in codes  # limit is 3/minute in this fixture
    assert codes[0] == 200  # first posts succeed


def test_serve_refuses_open_bind_without_token(tmp_path, monkeypatch, capsys):
    from lawradar.cli import main as cli_main

    monkeypatch.chdir(tmp_path)
    assert cli_main(["serve", "--host", "0.0.0.0"]) == 2
    assert "token" in capsys.readouterr().err.lower()
