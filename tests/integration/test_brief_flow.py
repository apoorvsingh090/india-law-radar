"""M15 acceptance: briefs via CLI and the web download endpoint."""
import threading
import urllib.error
import urllib.request

import pytest
import yaml

from lawradar.cli import main
from lawradar.db import store
from lawradar.web.server import build_server

V1 = (b"<html><body><h1>Brief Act</h1><h2>Section 1 - Scope</h2>"
      b"<p>A sufficiently long brief paragraph for the flow test.</p>"
      b"</body></html>")

MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "terms_review_status": "not_reviewed",
    "enabled": True, "rate_limit_seconds": 0,
}


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    data_dir = tmp_path / "data"
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [MANUAL]}), encoding="utf-8")
    target = tmp_path / "b.html"
    target.write_bytes(V1)
    assert main(["--data-dir", str(data_dir), "ingest", "m",
                 "--sources-file", str(sources), "--file", str(target),
                 "--title", "Brief Act", "--doc-id", "brief"]) == 0
    conn = store.connect(data_dir / "lawradar.db")
    try:
        rid = int(conn.execute(
            "SELECT id FROM change_reports ORDER BY id DESC LIMIT 1"
        ).fetchone()[0])
    finally:
        conn.close()
    yield data_dir, rid
    (tmp_path / "brief.md").unlink(missing_ok=True)


def _approve(data_dir, rid):
    return main(["--data-dir", str(data_dir), "review", str(rid),
                 "--approve", "--reviewer", "R", "--notes", "ok"])


def test_brief_refused_for_draft(seeded, capsys):
    data_dir, rid = seeded
    assert main(["--data-dir", str(data_dir), "reports", "brief",
                 str(rid)]) == 2
    assert "not approved" in capsys.readouterr().err


def test_brief_unknown_report_exits_1(seeded, capsys):
    data_dir, _ = seeded
    assert main(["--data-dir", str(data_dir), "reports", "brief",
                 "999"]) == 1
    assert "unknown report" in capsys.readouterr().err


def test_brief_stdout_and_out_file(seeded, capsys, tmp_path):
    data_dir, rid = seeded
    assert _approve(data_dir, rid) == 0
    capsys.readouterr()
    assert main(["--data-dir", str(data_dir), "reports", "brief",
                 str(rid)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Brief Act")
    assert f"**Change report #{rid}**" in out
    assert "not legal advice" in out

    target = tmp_path / "brief.md"
    assert main(["--data-dir", str(data_dir), "reports", "brief", str(rid),
                 "--out", str(target)]) == 0
    capsys.readouterr()
    assert target.read_text(encoding="utf-8").startswith("# Brief Act")


def test_brief_json(seeded, capsys):
    import json

    data_dir, rid = seeded
    assert _approve(data_dir, rid) == 0
    capsys.readouterr()
    assert main(["--data-dir", str(data_dir), "--json", "reports", "brief",
                 str(rid)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report_id"] == rid
    assert payload["bytes"] > 0
    assert payload["markdown"].startswith("# Brief Act")


def test_web_brief_download(seeded):
    data_dir, rid = seeded
    server = build_server(str(data_dir / "lawradar.db"),
                          host="127.0.0.1", port=0, token="")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(base + f"/reports/{rid}/brief.md",
                                   timeout=10)
        assert excinfo.value.code == 409  # draft

        assert _approve(data_dir, rid) == 0
        with urllib.request.urlopen(base + f"/reports/{rid}/brief.md",
                                    timeout=10) as resp:
            assert resp.status == 200
            assert resp.headers.get_content_type() == "text/markdown"
            disposition = resp.headers.get("Content-Disposition", "")
            assert f'filename="report-{rid}.md"' in disposition
            body = resp.read().decode("utf-8")
        assert body.startswith("# Brief Act")
        assert "not legal advice" in body

        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(base + "/reports/999/brief.md", timeout=10)
        assert excinfo.value.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=5)
