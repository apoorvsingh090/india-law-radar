"""M5 acceptance: all major functions end-to-end over the local DB.

Spins up the real stdlib server on an ephemeral loopback port: dashboard,
feed (+filters), report detail, document page, search, sources, review
queue, coverage, JSON API, token-gated review POSTs, and XSS escaping.
"""
import json
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

V1 = (b"<html><body><h1>Web Act</h1><h2>Section 1 - Scope</h2>"
      b"<p>Every establishment shall file the quarterly web return.</p>"
      b"</body></html>")
V2 = (b"<html><body><h1>Web Act</h1><h2>Section 1 - Scope</h2>"
      b"<p>Every establishment shall file the quarterly web return.</p>"
      b"<h2>Section 2 - Portal</h2><p>Filings go through the web portal.</p>"
      b"</body></html>")

MANUAL = {
    "id": "m", "name": "M", "base_url": "https://www.indiacode.nic.in/",
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

    def _ingest(payload, name, title="Web Act", doc_id="web-act"):
        target = tmp_path / name
        target.write_bytes(payload)
        assert main(["--data-dir", config.data_dir, "ingest", "m",
                     "--sources-file", str(sources), "--file", str(target),
                     "--title", title, "--doc-id", doc_id]) == 0

    _ingest(V1, "w1.html")
    _ingest(V2, "w2.html")
    # XSS probe: hostile title must be escaped everywhere it renders.
    _ingest(V1, "evil.html", title="<script>alert(1)</script>", doc_id="evil")

    server = build_server(str(tmp_path / "data" / "lawradar.db"),
                          host="127.0.0.1", port=0, token="secret")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(100):
        if server.server_address[1]:
            break
        time.sleep(0.05)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, tmp_path
    server.shutdown()
    thread.join(timeout=5)


def _get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _post(base, path, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(base + path, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def test_pages_and_api(live):
    base, _ = live
    for path, marker in [
        ("/", "India Law Radar"),
        ("/changes", "Web Act"),
        ("/changes?status=unverified", "Web Act"),
        ("/reports/1", "new_document"),
        ("/documents/1", "Web Act"),
        ("/search", "Search"),
        ("/search?q=quarterly", "Web Act"),
        ("/sources", "manual_import"),
        ("/review", "Review"),
        ("/coverage", "Limitations"),
        ("/health", "ok"),
    ]:
        status, body = _get(base, path)
        assert status == 200, path
        assert marker in body, f"{path} missing {marker!r}"
    assert "fully up to date" not in _get(base, "/")[1].lower()


def test_api_shapes(live):
    base, _ = live
    status, body = _get(base, "/api/reports")
    assert status == 200
    assert isinstance(json.loads(body), list)
    status, body = _get(base, "/api/search?q=portal")
    assert status == 200 and json.loads(body)
    status, body = _get(base, "/api/reports/9999")
    assert status == 404


def test_review_post_token_gated(live):
    base, tmp_path = live
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    rid = next(r["id"] for r in store.list_reports(conn)
               if r["change_type"] == "text_modified")
    conn.close()
    # No token -> 403, still unpublished.
    status, _ = _post(base, f"/reports/{rid}/review",
                      {"decision": "approved", "reviewer": "web"})
    assert status == 403
    # Bad decision value -> 400 even with token.
    status, _ = _post(base, f"/reports/{rid}/review",
                      {"decision": "maybe", "token": "secret"})
    assert status == 400
    # Reject without notes -> 400 (notes required).
    status, _ = _post(base, f"/reports/{rid}/review",
                      {"decision": "rejected", "token": "secret"})
    assert status == 400
    # Approve with token -> redirect, published.
    status, _ = _post(base, f"/reports/{rid}/review",
                      {"decision": "approved", "token": "secret",
                       "reviewer": "web", "notes": "checked"})
    assert status in (200, 303)
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    try:
        assert store.get_report(conn, rid)["published_at"]
    finally:
        conn.close()


def test_xss_escaped(live):
    base, _ = live
    _, body = _get(base, "/changes")
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
