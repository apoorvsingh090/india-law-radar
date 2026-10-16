"""Search tests: FTS indexing, snippets, fallback, injection safety."""
from lawradar.db import store
from lawradar.search import fts


def _seed(conn):
    store.upsert_source(conn, __import__(
        "lawradar.sources.registry",
        fromlist=["SourceRecord"]).SourceRecord(
            id="s", name="S", base_url="https://example.invalid/",
            access_method="manual_import", enabled=True))
    doc = store.get_or_create_document(
        conn, source_id="s", source_document_id="d1",
        title="Quarterly Returns Act", issuing_authority="Auth")
    ver = store.create_version(
        conn, document_id=doc, content_sha256="a" * 64,
        raw_storage_path=None, extracted_text_path=None,
        extraction_method="text", extraction_status="ok",
        parser_warnings=[])
    fts.upsert_index(conn, doc_id=doc, version_id=ver,
                     title="Quarterly Returns Act",
                     body="Every establishment shall file the quarterly "
                          "return within thirty days.")
    conn.commit()
    return doc


def test_fts_finds_body_text(tmp_path):
    fts.reset_cache()
    path = tmp_path / "s.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        _seed(conn)
        assert fts.fts_available(conn)
        hits = fts.search(conn, "quarterly")
        assert len(hits) == 1 and hits[0]["engine"] == "fts"
        assert "quarterly" in hits[0]["snippet"].lower()
    finally:
        conn.close()


def test_empty_query_returns_nothing(tmp_path):
    fts.reset_cache()
    path = tmp_path / "s.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        _seed(conn)
        assert fts.search(conn, "   ") == []
    finally:
        conn.close()


def test_fts_syntax_characters_treated_literally(tmp_path):
    fts.reset_cache()
    path = tmp_path / "s.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        _seed(conn)
        # Would raise `no such column` under naive MATCH interpolation.
        assert fts.search(conn, 'quarterly" OR 1=1 --') == []
    finally:
        conn.close()


def test_like_fallback_without_fts(tmp_path, monkeypatch):
    fts.reset_cache()
    path = tmp_path / "s.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        _seed(conn)
        monkeypatch.setattr(fts, "fts_available", lambda conn: False)
        hits = fts.search(conn, "establishment")
        assert len(hits) == 1 and hits[0]["engine"] == "like"
    finally:
        conn.close()


def test_reindex_rebuilds(tmp_path):
    fts.reset_cache()
    path = tmp_path / "s.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        doc = _seed(conn)
        conn.execute("DELETE FROM search_index")
        conn.commit()
        assert fts.search(conn, "quarterly") == []
        assert fts.reindex(conn) == 1
        assert len(fts.search(conn, "quarterly")) == 1
        assert fts.ensure_indexed(conn) == 0  # nothing missing
    finally:
        conn.close()
