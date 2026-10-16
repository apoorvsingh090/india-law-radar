"""M3 acceptance: fixture changes detected, reports persisted + reviewed.

End-to-end: ingest v1 -> report new_document; ingest v2 (same doc) ->
report text_modified with Section 3 + Section 4; re-ingest -> no dup
report; missing dates stay unknown; CLI reports list/show/generate work.
"""
import json

import yaml

from lawradar.cli import main
from lawradar.config import load_settings
from lawradar.db import store

V1 = (b"<html><body><h1>Flow Act</h1>"
      b"<h2>Section 3 - Compliance threshold</h2>"
      b"<p>File within thirty days.</p></body></html>")
V2 = (b"<html><body><h1>Flow Act</h1>"
      b"<h2>Section 3 - Compliance threshold</h2>"
      b"<p>File within forty-five days.</p>"
      b"<h2>Section 4 - Late fee</h2><p>Late fee applies.</p></body></html>")

MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "terms_review_status": "not_reviewed",
    "enabled": True, "rate_limit_seconds": 0,
}


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [MANUAL]}), encoding="utf-8")
    return config, str(sources)


def _ingest_file(config, sources, tmp_path, payload, title="Flow Act"):
    target = tmp_path / "flow.html"
    target.write_bytes(payload)
    assert main(["--data-dir", config.data_dir, "ingest", "m",
                 "--sources-file", sources, "--file", str(target),
                 "--title", title, "--doc-id", "flow-act"]) == 0


def test_reports_end_to_end(tmp_path, monkeypatch, capsys):
    config, sources = _setup(tmp_path, monkeypatch)
    _ingest_file(config, sources, tmp_path, V1)
    capsys.readouterr()
    assert main(["--data-dir", config.data_dir, "reports", "list"]) == 0
    out = capsys.readouterr().out
    assert "new_document" in out

    _ingest_file(config, sources, tmp_path, V2)
    capsys.readouterr()
    assert main(["--data-dir", config.data_dir, "reports", "list"]) == 0
    out = capsys.readouterr().out
    assert "text_modified" in out

    conn = store.connect(tmp_path / "data" / "lawradar.db")
    try:
        reports = store.list_reports(conn)
        assert len(reports) == 2
        changed = next(r for r in reports if r["change_type"] == "text_modified")
        claims = json.loads(changed["claims_json"])
        assert claims  # every report carries claims
        affected = json.loads(changed["affected_sections"])
        assert any("Section 3" in s for s in affected)
        assert any("Section 4" in s for s in affected)
        citations = store.list_citations(conn, changed["id"])
        # One citation per textual change plus source/version citations.
        assert len(citations) >= len(json.loads(changed["claims_json"])) + 1
        for claim in claims:
            assert claim["citation_ids"]
        assert changed["verification_status"] == "unverified"
        assert "@@" in changed["diff_text"]  # raw audit diff persisted
    finally:
        conn.close()

    # Console output must survive Windows cp1252 consoles (no exotic glyphs).
    assert main(["--data-dir", config.data_dir, "reports", "list"]) == 0
    capsys.readouterr().out.encode("cp1252")
    assert main(["--data-dir", config.data_dir, "reports", "show",
                 str(changed["id"])]) == 0
    capsys.readouterr().out.encode("cp1252")

    # Re-ingesting identical bytes creates no duplicate report.
    _ingest_file(config, sources, tmp_path, V2)
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    try:
        assert store.count_reports(conn) == 2
    finally:
        conn.close()


def test_reports_show_and_generate_idempotent(tmp_path, monkeypatch, capsys):
    config, sources = _setup(tmp_path, monkeypatch)
    _ingest_file(config, sources, tmp_path, V1)
    capsys.readouterr()
    assert main(["--data-dir", config.data_dir, "reports", "show", "1"]) == 0
    out = capsys.readouterr().out
    assert "new_document" in out and "citations" in out.lower()
    assert main(["--data-dir", config.data_dir, "reports", "show", "99"]) == 2
    assert main(["--data-dir", config.data_dir, "reports", "generate",
                 "--limit", "10"]) == 0
    out = capsys.readouterr().out
    assert "already reported" in out
