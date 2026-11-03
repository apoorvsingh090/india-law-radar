"""M19 acceptance: documents browser page + filtered web search."""
import threading
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
    from lawradar.sources.registry import SourceRecord

    data_dir = tmp_path / "data"
    path = data_dir / "lawradar.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        store.upsert_source(conn, SourceRecord(
            id="s", name="S", base_url="https://example.invalid/",
            access_method="manual_import", enabled=True))
        act = store.get_or_create_document(
            conn, source_id="s", source_document_id="act",
            title="Filing Act", document_type="Act",
            jurisdiction="central", official_url="https://example.invalid/a")
        rule = store.get_or_create_document(
            conn, source_id="s", source_document_id="rule",
            title="Filing Rules", document_type="Rule",
            jurisdiction="state", official_url="https://example.invalid/r")
        from lawradar.search import fts

        for index, (doc, body) in enumerate(
                ((act, "Filing deadlines and forms."),
                 (rule, "Central filing procedure for offices.")), start=1):
            ver = store.create_version(
                conn, document_id=doc, content_sha256=f"{index:064d}",
                raw_storage_path=None, extracted_text_path=None,
                extraction_method="text", extraction_status="ok",
                parser_warnings=[])
            fts.upsert_index(conn, doc_id=doc, version_id=ver,
                             title="Filing Act" if index == 1
                             else "Filing Rules", body=body)
        conn.commit()
    finally:
        conn.close()
    server = build_server(str(path), host="127.0.0.1", port=0, token="")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        assert resp.status == 200
        return resp.read().decode("utf-8")


def test_documents_page_lists_and_filters(seeded):
    html = _get(seeded, "/documents")
    assert "Filing Act" in html and "Filing Rules" in html
    assert "2 document(s)" in html
    assert 'href="/documents"' in html  # nav link

    act_only = _get(seeded, "/documents?type=Act")
    assert "Filing Act" in act_only and "Filing Rules" not in act_only
    assert "type=Act" in act_only

    state_only = _get(seeded, "/documents?jurisdiction=state")
    assert "Filing Rules" in state_only
    assert "Filing Act" not in state_only

    empty = _get(seeded, "/documents?source=ghost")
    assert "No documents match these filters." in empty


def test_search_page_filters(seeded):
    query = urllib.parse.urlencode({"q": "Filing", "type": "Rule"})
    html = _get(seeded, f"/search?{query}")
    assert "Filing Rules" in html
    assert "1 result(s)" in html
    assert 'name="type"' in html  # filter selects present
    assert 'selected' in html  # the active value is preselected

    plain = _get(seeded, "/search?q=Filing")
    assert "2 result(s)" in plain
