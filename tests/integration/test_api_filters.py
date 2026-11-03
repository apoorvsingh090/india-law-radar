"""M21 acceptance: JSON API filter parity (/api/documents, reports, search)."""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from lawradar.db import store
from lawradar.web.server import build_server


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    from lawradar.search import fts
    from lawradar.sources.registry import SourceRecord

    path = tmp_path / "data" / "lawradar.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        store.upsert_source(conn, SourceRecord(
            id="s", name="S", base_url="https://example.invalid/",
            access_method="manual_import", enabled=True))
        act = store.get_or_create_document(
            conn, source_id="s", source_document_id="act",
            title="Filing Act", document_type="Act",
            jurisdiction="central")
        rule = store.get_or_create_document(
            conn, source_id="s", source_document_id="rule",
            title="Filing Rules", document_type="Rule",
            jurisdiction="state")
        for index, doc, body in ((1, act, "Filing deadlines."),
                                 (2, rule, "Filing office procedure.")):
            ver = store.create_version(
                conn, document_id=doc, content_sha256=f"{index:064d}",
                raw_storage_path=None, extracted_text_path=None,
                extraction_method="text", extraction_status="ok",
                parser_warnings=[])
            report = store.create_report(
                conn, document_id=doc, old_version_id=None,
                new_version_id=ver, change_type="new_document",
                summary="First version.", claims=[])
            if index == 2:
                conn.execute(
                    "UPDATE change_reports SET verification_status='approved' "
                    "WHERE id=?", (report,))
            fts.upsert_index(conn, doc_id=doc, version_id=ver,
                             title=f"Filing {'Act' if index == 1 else 'Rules'}",
                             body=body)
        conn.commit()
    finally:
        conn.close()
    server = build_server(str(path), host="127.0.0.1", port=0, token="")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)


def _json(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_api_documents_filters(seeded):
    status, rows = _json(seeded, "/api/documents")
    assert status == 200 and len(rows) == 2

    status, rows = _json(seeded, "/api/documents?type=Act")
    assert status == 200
    assert [r["title"] for r in rows] == ["Filing Act"]

    status, rows = _json(seeded, "/api/documents?jurisdiction=state&limit=1")
    assert status == 200
    assert [r["title"] for r in rows] == ["Filing Rules"]

    status, payload = _json(seeded, "/api/documents?limit=0")
    assert status == 400 and "limit" in payload["error"]


def test_api_reports_filters(seeded):
    status, rows = _json(seeded, "/api/reports?status=approved")
    assert status == 200 and len(rows) == 1
    assert rows[0]["document_title"] == "Filing Rules"

    status, rows = _json(seeded, "/api/reports?type=Rule")
    assert status == 200 and len(rows) == 1

    status, rows = _json(seeded, "/api/reports?since=2999-01-01")
    assert status == 200 and rows == []

    status, payload = _json(seeded, "/api/reports?since=03-11-2026")
    assert status == 400 and "since" in payload["error"]


def test_api_search_filters(seeded):
    query = urllib.parse.urlencode({"q": "Filing", "type": "Rule"})
    status, rows = _json(seeded, f"/api/search?{query}")
    assert status == 200
    assert [r["title"] for r in rows] == ["Filing Rules"]

    status, rows = _json(seeded, "/api/search?q=Filing")
    assert status == 200 and len(rows) == 2
