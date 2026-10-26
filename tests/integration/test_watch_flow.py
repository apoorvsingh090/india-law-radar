"""M8 acceptance: `lawradar watch --once` end-to-end and the /feed.xml
publication gate — only human-approved reports ever reach the feed.
"""
import threading
import time
import urllib.error
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


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [FIXTURE]}),
                       encoding="utf-8")
    return config, str(sources), tmp_path


def test_watch_once_ingests_and_skips_manual(env, capsys):
    config, _sources_file, tmp_path = env
    registry = yaml.safe_dump({
        "sources": [FIXTURE, {
            "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
            "access_method": "manual_import", "enabled": True,
            "rate_limit_seconds": 0, "poll_interval_minutes": 10080}]})
    path = tmp_path / "sources-with-manual.yaml"
    path.write_text(registry, encoding="utf-8")
    assert main(["--data-dir", config.data_dir, "watch", "--once",
                 "--sources-file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "fx: success" in out
    assert "m: skipped (manual_import" in out
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    try:
        assert len(store.list_documents(conn)) == 2
    finally:
        conn.close()


def test_watch_once_respects_interval_and_exits_nonzero_on_failure(
        env, capsys):
    config, sources_file, tmp_path = env
    assert main(["--data-dir", config.data_dir, "watch", "--once",
                 "--sources-file", sources_file]) == 0
    capsys.readouterr()  # discard the first sweep's output
    # Immediately again: fixture not due, nothing ingested, exit stays 0.
    assert main(["--data-dir", config.data_dir, "watch", "--once",
                 "--sources-file", sources_file]) == 0
    out = capsys.readouterr().out
    assert "fx: skipped (not due until" in out
    assert "fx: success" not in out
    # A broken http_poll source makes --once exit 1 (scheduler signal).
    broken = yaml.safe_dump({"sources": [{
        "id": "dead", "name": "Dead", "base_url": "https://example.invalid/",
        "access_method": "http_poll", "enabled": True,
        "rate_limit_seconds": 0, "poll_interval_minutes": 1440,
        "storage_policy": "unknown", "terms_review_status": "not_reviewed"}]})
    path = tmp_path / "broken.yaml"
    path.write_text(broken, encoding="utf-8")
    assert main(["--data-dir", config.data_dir, "watch", "--once",
                 "--sources-file", str(path)]) == 1


def test_feed_only_shows_published(env):
    config, sources_file, tmp_path = env
    assert main(["--data-dir", config.data_dir, "watch", "--once",
                 "--sources-file", sources_file]) == 0
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    reports = store.list_reports(conn)
    assert reports and all(r["published_at"] is None for r in reports)
    conn.close()

    server = build_server(str(tmp_path / "data" / "lawradar.db"),
                          host="127.0.0.1", port=0, token="")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(100):
        if server.server_address[1]:
            break
        time.sleep(0.05)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        # Unpublished drafts: valid Atom, zero entries, no titles leak.
        with urllib.request.urlopen(base + "/feed.xml", timeout=10) as resp:
            assert resp.status == 200
            assert "atom+xml" in resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8")
        assert "<entry>" not in body
        assert "Sample Act" not in body
        # Approve one report; it — and only it — appears.
        conn = store.connect(tmp_path / "data" / "lawradar.db")
        rid = store.list_reports(conn)[0]["id"]
        conn.close()
        assert main(["--data-dir", config.data_dir, "review", str(rid),
                     "--approve", "--reviewer", "feed-test",
                     "--notes", "checked against fixture"]) == 0
        with urllib.request.urlopen(base + "/feed.xml", timeout=10) as resp:
            body = resp.read().decode("utf-8")
        assert body.count("<entry>") == 1
        assert "[FIXTURE]" in body
        # Feed autodiscovery link on HTML pages (M8 nav).
        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            home = resp.read().decode("utf-8")
        assert 'href="/feed.xml"' in home
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"unexpected HTTP {exc.code}") from exc
    finally:
        server.shutdown()
        thread.join(timeout=5)
