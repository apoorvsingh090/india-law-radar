"""M12 acceptance: evidence export through the real CLI flow.

End-to-end: ingest two versions -> approve -> bundles create exports a
verifiable zip (with the stored original) -> bundles verify passes
(text and --json) -> bundles list prints the audit trail -> the report
page shows the Evidence bundles section -> a tampered zip fails verify
with exit 1 -> a draft report is refused with exit 2 -> unknown report
exits 1 -> verify of a nonexistent bundle exits 1.
"""
import json
import threading
import urllib.request
import zipfile

import pytest
import yaml

from lawradar.cli import main
from lawradar.db import store
from lawradar.evidence.bundle import REPORT_MEMBER, verify_bundle

V1 = (b"<html><body><h1>Bundle Act</h1>"
      b"<h2>Section 1 - Short title</h2>"
      b"<p>This is a sufficiently long first version text for bundle.</p>"
      b"</body></html>")
V2 = (b"<html><body><h1>Bundle Act</h1>"
      b"<h2>Section 1 - Short title</h2>"
      b"<p>This is a sufficiently long second version text for bundle.</p>"
      b"<h2>Section 2 - Added provision</h2>"
      b"<p>An additional provision with enough words to extract.</p>"
      b"</body></html>")

MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "terms_review_status": "not_reviewed",
    "enabled": True, "rate_limit_seconds": 0,
}


@pytest.fixture()
def approved_report(tmp_path, monkeypatch, capsys):
    """Two versions ingested + approved; returns (data_dir, report_id, draft_id)."""
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    data_dir = tmp_path / "data"
    sources = tmp_path / "sources.yaml"
    sources.write_text(yaml.safe_dump({"sources": [MANUAL]}),
                       encoding="utf-8")
    for index, payload in ((1, V1), (2, V2)):
        target = tmp_path / f"v{index}.html"
        target.write_bytes(payload)
        assert main(["--data-dir", str(data_dir), "ingest", "m",
                     "--sources-file", str(sources), "--file", str(target),
                     "--title", "Bundle Act",
                     "--doc-id", "bundle-act"]) == 0
    capsys.readouterr()
    conn = store.connect(data_dir / "lawradar.db")
    changed = next(r for r in store.list_reports(conn)
                   if r["change_type"] == "text_modified")
    drafts = [r for r in store.list_reports(conn)
              if r["change_type"] == "new_document"]
    rid = changed["id"]
    conn.close()
    assert main(["--data-dir", str(data_dir), "review", str(rid),
                 "--approve", "--reviewer", "Test Reviewer",
                 "--notes", "compared against the fixture"]) == 0
    capsys.readouterr()
    return data_dir, rid, drafts[0]["id"] if drafts else None


def _latest_zip(data_dir):
    zips = sorted((data_dir / "bundles").glob("*.zip"))
    assert zips, "no bundle exported"
    return zips[-1]


def test_export_and_verify_roundtrip(tmp_path, approved_report, capsys):
    data_dir, rid, _ = approved_report
    assert main(["--data-dir", str(data_dir), "bundles", "create",
                 str(rid)]) == 0
    out = capsys.readouterr().out
    assert "document: included" in out
    zip_path = _latest_zip(data_dir)
    verified = verify_bundle(zip_path)
    assert verified.report_id == rid and verified.has_document

    assert main(["--data-dir", str(data_dir), "bundles", "verify",
                 str(zip_path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "bundle: OK " + zip_path.name
    assert any("document_sha256" in line for line in lines)

    assert main(["--data-dir", str(data_dir), "--json", "bundles",
                 "verify", str(zip_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report_id"] == rid
    assert payload["has_document"] is True

    with zipfile.ZipFile(zip_path) as zf:
        member = json.loads(zf.read(REPORT_MEMBER))
    assert member["report"]["published_at"]
    assert member["document"]["title"] == "Bundle Act"
    history = member["review_history"]
    assert history and history[0]["status"] == "approved"


def test_list_and_report_page(tmp_path, approved_report, capsys):
    data_dir, rid, _ = approved_report
    assert main(["--data-dir", str(data_dir), "bundles", "create",
                 str(rid)]) == 0
    capsys.readouterr()
    assert main(["--data-dir", str(data_dir), "bundles", "list"]) == 0
    out = capsys.readouterr().out
    assert f"report={rid}" in out and "doc included" in out
    assert main(["--data-dir", str(data_dir), "--json", "bundles",
                 "list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows and rows[0]["change_report_id"] == rid

    from lawradar.web.server import build_server

    server = build_server(str(data_dir / "lawradar.db"),
                          host="127.0.0.1", port=0, token="")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(f"{base}/reports/{rid}",
                                    timeout=10) as resp:
            html = resp.read().decode("utf-8", "replace")
        assert "Evidence bundles" in html
        assert f"lawradar bundles create {rid}" in html
        with urllib.request.urlopen(
                f"{base}/api/bundles?report={rid}", timeout=10) as resp:
            api_rows = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert len(api_rows) == 1 and api_rows[0]["change_report_id"] == rid


def test_refusals(tmp_path, approved_report, capsys):
    data_dir, rid, draft_id = approved_report
    # Draft report cannot become evidence (policy refusal, exit 2).
    assert main(["--data-dir", str(data_dir), "bundles", "create",
                 str(draft_id)]) == 2
    # Unknown report id is an input error, not a policy refusal.
    assert main(["--data-dir", str(data_dir), "bundles", "create",
                 "999"]) == 1
    assert list((data_dir / "bundles").glob("*.zip")) == []
    assert "not approved yet" in capsys.readouterr().err

    # A tampered bundle fails verification with exit 1.
    assert main(["--data-dir", str(data_dir), "bundles", "create",
                 str(rid)]) == 0
    capsys.readouterr()
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(_latest_zip(data_dir)) as zf:
        payload = {n: zf.read(n) for n in zf.namelist()}
    payload[REPORT_MEMBER] = b'{"report": {"id": 9001}}'
    with zipfile.ZipFile(tampered, "w") as zf:
        for name, blob in sorted(payload.items()):
            zf.writestr(name, blob)
    assert main(["--data-dir", str(data_dir), "bundles", "verify",
                 str(tampered)]) == 1
    assert main(["--data-dir", str(data_dir), "bundles", "verify",
                 str(tmp_path / "missing.zip")]) == 1

    # Sanity: the same app just verified a real export successfully.
    assert main(["--data-dir", str(data_dir), "bundles", "verify",
                 str(_latest_zip(data_dir))]) == 0
