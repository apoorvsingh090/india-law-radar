"""M11 acceptance: approval fan-out through the real CLI + web flow.

End-to-end: ingest two versions -> approve with two webhook targets (one
healthy, one HTTP 500) -> delivered + failed attempts recorded, approval
never blocked -> notify list shows both -> notify send retries the
healthy receiver and repeats stay deduplicated -> disabled setups never
record attempts -> the receiver verifies the HMAC signature header.
"""
import hashlib
import hmac as hmac_mod
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

from lawradar.cli import main
from lawradar.db import store

SECRET = "test-signing-secret"
V1 = (b"<html><body><h1>Notify Act</h1>"
      b"<h2>Section 1 - Short title</h2>"
      b"<p>This is a sufficiently long first version text for notify.</p>"
      b"</body></html>")
V2 = (b"<html><body><h1>Notify Act</h1>"
      b"<h2>Section 1 - Short title</h2>"
      b"<p>This is a sufficiently long second version text for notify.</p>"
      b"<h2>Section 2 - Added provision</h2>"
      b"<p>An additional provision with enough words to extract.</p>"
      b"</body></html>")

MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "terms_review_status": "not_reviewed",
    "enabled": True, "rate_limit_seconds": 0,
}


class _Receiver(BaseHTTPRequestHandler):
    """Records deliveries; /ok answers 200, /flaky fails until flipped."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        record = {
            "path": self.path,
            "body": body,
            "token": self.headers.get("X-LawRadar-Token", ""),
            "event": self.headers.get("X-LawRadar-Event", ""),
            "ua": self.headers.get("User-Agent", ""),
        }
        _Receiver.deliveries.append(record)
        if (self.path == "/flaky" and not _Receiver.flaky_ok):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"receiver exploded")
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"received": true}')

    def log_message(self, *args):
        pass


@pytest.fixture()
def receiver():
    _Receiver.deliveries = []
    _Receiver.flaky_ok = False
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield url
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _settings(tmp_path, db_path, webhooks, enabled=True):
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    settings = {
        "data_dir": str(tmp_path / "data"),
        "db_url": f"sqlite:///{db_path}",
        "notify_enabled": enabled,
        "notify_timeout_seconds": 5,
        "notify_webhooks": webhooks,
    }
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump(settings), encoding="utf-8")


def _deliveries(conn, report_id=None):
    return store.list_notification_attempts(conn, change_report_id=report_id)


def test_approval_fans_out_to_webhooks(tmp_path, monkeypatch, capsys,
                                       receiver):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE",
                "LAWRADAR_NOTIFY_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    db_path = tmp_path / "data" / "lawradar.db"
    _settings(tmp_path, db_path, [
        {"name": "good", "url": f"{receiver}/ok", "secret": SECRET},
        {"name": "sink", "url": f"{receiver}/flaky"}])
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [MANUAL]}), encoding="utf-8")

    for index, payload in ((1, V1), (2, V2)):
        target = tmp_path / f"n{index}.html"
        target.write_bytes(payload)
        assert main(["--data-dir", str(tmp_path / "data"), "ingest", "m",
                     "--sources-file", str(sources), "--file", str(target),
                     "--title", "Notify Act",
                     "--doc-id", "notify-act"]) == 0
    capsys.readouterr()

    conn = store.connect(db_path)
    changed = next(r for r in store.list_reports(conn)
                   if r["change_type"] == "text_modified")
    rid = changed["id"]
    conn.close()

    # Approve: publication must succeed even though one target 500s, and
    # failures are recorded rather than raised.
    assert main(["--data-dir", str(tmp_path / "data"), "review", str(rid),
                 "--approve", "--reviewer", "Test Reviewer",
                 "--notes", "checked against fixture"]) == 0
    out = capsys.readouterr().out
    assert "approved" in out
    assert "1 delivered" in out and "1 failed" in out

    conn = store.connect(db_path)
    rows = _deliveries(conn, rid)
    status = {r["webhook"]: r["status"] for r in rows}
    assert status == {"good": "delivered", "sink": "failed"}
    report = store.get_report(conn, rid)
    assert report["published_at"]  # approval was never blocked
    conn.close()

    # The receiver saw one POST per target: /ok delivered and signed,
    # /flaky refused (HTTP 500) and recorded as failed, approval intact.
    paths = sorted(d["path"] for d in _Receiver.deliveries)
    assert paths == ["/flaky", "/ok"]
    delivery = next(d for d in _Receiver.deliveries if d["path"] == "/ok")
    assert delivery["event"] == "report.approved"
    assert "webhook-dispatch" in delivery["ua"]
    payload = json.loads(delivery["body"])
    assert payload["report_id"] == rid
    assert payload["document_title"] == "Notify Act"
    assert payload["verification_status"] == "approved"
    token_ts, token_v1 = delivery["token"].replace("t=", "").split(",v1=")
    expected = hmac_mod.new(
        SECRET.encode(), f"{token_ts}.".encode() + delivery["body"],
        hashlib.sha256).hexdigest()
    assert token_v1 == expected  # receiver can verify authenticity
    unsigned = next(d for d in _Receiver.deliveries if d["path"] == "/flaky")
    assert unsigned["token"] == ""  # no secret configured for that target

    # audit: notify list shows both attempts, then send retries only the
    # failing target (the healthy one is deduplicated, not re-POSTed).
    assert main(["--data-dir", str(tmp_path / "data"), "notify", "list"]) == 0
    listing = capsys.readouterr().out
    assert "webhook=good delivered" in listing
    assert "webhook=sink failed" in listing

    _Receiver.flaky_ok = True  # operator fixes the receiver
    assert main(["--data-dir", str(tmp_path / "data"), "notify", "send",
                 "--report", str(rid)]) == 0
    out = capsys.readouterr().out
    assert "good: deduplicated" in out and "sink: delivered" in out
    conn = store.connect(db_path)
    rows = _deliveries(conn, rid)
    # good: exactly one delivered attempt (never re-POSTed); sink: one
    # failed then one delivered by the retry.
    by_target: dict[str, list[str]] = {}
    for row in sorted(rows, key=lambda r: r["id"]):  # chronological
        states = by_target.setdefault(row["webhook"], [])
        if row["status"] in ("delivered", "failed"):
            states.append(row["status"])
    assert by_target == {"good": ["delivered"],
                         "sink": ["failed", "delivered"]}
    conn.close()
    paths = sorted(d["path"] for d in _Receiver.deliveries)
    assert paths == ["/flaky", "/flaky", "/ok"]

    # Sweeping again is a no-op: every published target is delivered.
    assert main(["--data-dir", str(tmp_path / "data"), "notify", "send"]) == 0
    assert "Nothing outstanding" in capsys.readouterr().out


def test_disabled_setup_records_no_attempts(tmp_path, monkeypatch, capsys,
                                            receiver):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    db_path = tmp_path / "data" / "lawradar.db"
    _settings(tmp_path, db_path, [], enabled=False)
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [MANUAL]}), encoding="utf-8")
    for index, payload in ((1, V1), (2, V2)):
        target = tmp_path / f"n{index}.html"
        target.write_bytes(payload)
        assert main(["--data-dir", str(tmp_path / "data"), "ingest", "m",
                     "--sources-file", str(sources), "--file", str(target),
                     "--title", "Notify Act",
                     "--doc-id", "notify-act-dis"]) == 0
    capsys.readouterr()
    conn = store.connect(db_path)
    rid = next(r["id"] for r in store.list_reports(conn, limit=1))
    conn.close()
    assert main(["--data-dir", str(tmp_path / "data"), "review", str(rid),
                 "--approve", "--reviewer", "R", "--notes", "ok"]) == 0
    out = capsys.readouterr().out
    assert "notifications" not in out  # silent when the feature is off
    assert len(_Receiver.deliveries) == 0
    conn = store.connect(db_path)
    assert _deliveries(conn) == []
    conn.close()
    # Explicit send with the feature off refuses and explains itself.
    assert main(["--data-dir", str(tmp_path / "data"), "notify", "send"]) == 2
    assert "disabled" in capsys.readouterr().err
