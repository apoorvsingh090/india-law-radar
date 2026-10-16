"""M4 acceptance: produce + verify + review a report without any LLM.

End-to-end: ingest two versions -> draft reports exist, unpublished ->
citation verify passes -> review approve publishes with audit trail ->
reject without notes fails -> heuristic summarise works ->
--ai without config fails cleanly.
"""
import json

import yaml

from lawradar.cli import main
from lawradar.config import load_settings
from lawradar.db import store

V1 = (b"<html><body><h1>Review Act</h1>"
      b"<h2>Section 1 - Short title</h2>"
      b"<p>This is a sufficiently long first version text for review.</p>"
      b"</body></html>")
V2 = (b"<html><body><h1>Review Act</h1>"
      b"<h2>Section 1 - Short title</h2>"
      b"<p>This is a sufficiently long second version text for review.</p>"
      b"<h2>Section 2 - Added provision</h2>"
      b"<p>An additional provision with enough words to extract.</p>"
      b"</body></html>")

MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "terms_review_status": "not_reviewed",
    "enabled": True, "rate_limit_seconds": 0,
}


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE",
                "LAWRADAR_AI_ENABLED", "LAWRADAR_AI_COMMAND"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [MANUAL]}), encoding="utf-8")
    return config, str(sources)


def _ingest(config, sources, tmp_path, payload, name="r.html"):
    target = tmp_path / name
    target.write_bytes(payload)
    assert main(["--data-dir", config.data_dir, "ingest", "m",
                 "--sources-file", sources, "--file", str(target),
                 "--title", "Review Act", "--doc-id", "review-act"]) == 0


def test_review_flow_end_to_end(tmp_path, monkeypatch, capsys):
    config, sources = _setup(tmp_path, monkeypatch)
    _ingest(config, sources, tmp_path, V1)
    _ingest(config, sources, tmp_path, V2)
    capsys.readouterr()

    # Drafts exist but nothing is published without human review.
    assert main(["--data-dir", config.data_dir, "reports", "list"]) == 0
    out = capsys.readouterr().out
    assert "unpublished" in out and "published_at" not in out.lower()

    conn = store.connect(tmp_path / "data" / "lawradar.db")
    changed = next(r for r in store.list_reports(conn)
                   if r["change_type"] == "text_modified")
    rid = changed["id"]
    conn.close()

    # Deterministic citation check passes on machine-generated citations.
    assert main(["--data-dir", config.data_dir, "reports", "verify",
                 str(rid)]) == 0
    out = capsys.readouterr().out
    assert "verified" in out

    # Rejecting without notes is refused; the report stays unpublished.
    assert main(["--data-dir", config.data_dir, "review", str(rid),
                 "--reject"]) == 1
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    assert not store.get_report(conn, rid)["published_at"]
    conn.close()

    # Approval with notes publishes and leaves an audit trail.
    assert main(["--data-dir", config.data_dir, "review", str(rid),
                 "--approve", "--reviewer", "Test Reviewer",
                 "--notes", "checked against fixture"]) == 0
    out = capsys.readouterr().out
    assert "approved" in out and "audit trail entries: 1" in out
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    row = store.get_report(conn, rid)
    assert row["verification_status"] == "approved" and row["published_at"]
    conn.close()

    # Heuristic rewording works with no model; --ai without config fails.
    assert main(["--data-dir", config.data_dir, "reports", "summarise",
                 str(rid)]) == 0
    assert main(["--data-dir", config.data_dir, "reports", "summarise",
                 str(rid), "--ai"]) == 1
    err = capsys.readouterr()
    assert "disabled" in (err.out + err.err).lower()

    # Queue shows the resolved decision, not pending work.
    assert main(["--data-dir", config.data_dir, "review", "--list"]) == 0
    out = capsys.readouterr().out
    assert "0 pending" in out


def test_auto_queue_flags_short_text(tmp_path, monkeypatch, capsys):
    config, sources = _setup(tmp_path, monkeypatch)
    _ingest(config, sources, tmp_path, b"<html><body><p>Hi</p></body></html>",
             name="short.html")
    capsys.readouterr()
    assert main(["--data-dir", config.data_dir, "review", "--list"]) == 0
    out = capsys.readouterr().out
    assert "1 pending" in out and "unreadable extraction" in out
    conn = store.connect(tmp_path / "data" / "lawradar.db")
    summary = json.loads(conn.execute(
        "SELECT ai_attempts FROM change_reports").fetchone()[0])
    assert summary == []  # no AI involved, no attempts recorded
    conn.close()
