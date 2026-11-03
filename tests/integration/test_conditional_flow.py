"""M13 acceptance flow: conditional HTTP polling with cached validators.

- First sweep fetches the probe URL, stores its ETag + last-validated time.
- Second sweep answers 304: run succeeds, nothing downloaded, no new
  version, and the source stays healthy.
- Server content revision bumps the ETag: next sweep downloads again and
  records the new validator.
"""
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

from lawradar.ingestion.pipeline import run_ingestion


class _PollHandler(BaseHTTPRequestHandler):
    """Tiny official-source stand-in with ETag-based conditionality."""

    revision = 1

    def log_message(self, *args):  # noqa: ANN001 - silence test server logs
        pass

    def do_GET(self):  # noqa: N802
        if self.path != "/notice":
            self.send_response(404)
            self.end_headers()
            return
        current = type(self).revision
        if self.headers.get("If-None-Match") == f'"v{current}"':
            self.send_response(304)
            self.end_headers()
            return
        body = ("<html><body><h1>Notice</h1>"
                f"<p>Revision {current} text.</p></body></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("ETag", f'"v{current}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def poll_setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    httpd = HTTPServer(("127.0.0.1", 0), _PollHandler)
    _PollHandler.revision = 1
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    config = load_test_config(tmp_path)
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [{
        "id": "poll-sample", "name": "Poll sample",
        "base_url": f"http://127.0.0.1:{httpd.server_port}/notice",
        "access_method": "http_poll", "terms_review_status": "reviewed_ok",
        "enabled": True, "rate_limit_seconds": 0,
    }]}), encoding="utf-8")
    yield config, str(sources)
    httpd.shutdown()


def load_test_config(tmp_path):
    from lawradar.config import load_settings

    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    return config


def _db(config):
    return sqlite3.connect(
        config.db_url.replace("sqlite:///", ""), timeout=10)


def test_conditional_polling_roundtrip(poll_setup):
    config, sources = poll_setup
    first = run_ingestion(config, sources, source_id="poll-sample")["runs"][0]
    assert first["status"] == "success"
    assert first["downloaded"] == 1 and first["changed"] == 1

    db = _db(config)
    try:
        etag, validated = db.execute(
            "SELECT http_etag, http_validated_at FROM documents"
        ).fetchone()
        assert etag == '"v1"'
        assert validated

        second = run_ingestion(
            config, sources, source_id="poll-sample")["runs"][0]
        assert second["status"] == "success"
        assert second["unchanged"] == 1
        assert second["downloaded"] == 0 and second["changed"] == 0
        versions = db.execute(
            "SELECT COUNT(*) FROM document_versions").fetchone()[0]
        assert versions == 1
        etag2, validated2 = db.execute(
            "SELECT http_etag, http_validated_at FROM documents"
        ).fetchone()
        assert etag2 == '"v1"'
        assert validated2 >= validated  # validator refresh stamped

        _PollHandler.revision = 2
        third = run_ingestion(
            config, sources, source_id="poll-sample")["runs"][0]
        assert third["status"] == "success"
        assert third["downloaded"] == 1 and third["changed"] == 1
        versions = db.execute(
            "SELECT COUNT(*) FROM document_versions").fetchone()[0]
        assert versions == 2
        etag3 = db.execute("SELECT http_etag FROM documents").fetchone()[0]
        assert etag3 == '"v2"'
    finally:
        db.close()
