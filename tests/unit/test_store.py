"""Durable SQLite connections (Milestone 17): WAL, busy timeout, FKs."""
import sqlite3
import threading

import pytest

from lawradar.db import store


def test_connection_pragmas(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # 1 == NORMAL
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        conn.close()


def test_foreign_keys_actually_enforced(tmp_path):
    path = tmp_path / "t.db"
    store.init_db(path)
    conn = store.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO documents (source_id, source_document_id, title) "
                "VALUES ('no-such-source', 'x', 't')")
    finally:
        conn.close()


def test_write_waits_for_competing_writer(tmp_path):
    """busy_timeout turns a momentary lock collision into a short wait."""
    path = tmp_path / "t.db"
    store.init_db(path)
    holder = store.connect(path)
    done: dict[str, bool] = {}
    try:
        holder.execute("INSERT INTO _meta (k, v) VALUES ('holder', '1')")

        def _compete() -> None:
            conn = store.connect(path)  # connections are per-thread
            try:
                conn.execute(
                    "INSERT INTO _meta (k, v) VALUES ('waiter', '2')")
                conn.commit()
                done["ok"] = True
            finally:
                conn.close()

        thread = threading.Thread(target=_compete)
        thread.start()
        thread.join(0.2)  # still blocked by the holder's open transaction
        assert not done
        holder.commit()
        thread.join(10)
        assert done.get("ok")
        reader = store.connect(path)
        try:
            rows = reader.execute("SELECT k FROM _meta ORDER BY k").fetchall()
        finally:
            reader.close()
        assert [row["k"] for row in rows] == ["holder", "waiter"]
    finally:
        holder.close()


def _seed_two_documents(path):
    from lawradar.sources.registry import SourceRecord

    store.init_db(path)
    conn = store.connect(path)
    store.upsert_source(conn, SourceRecord(
        id="s", name="S", base_url="https://example.invalid/",
        access_method="manual_import", enabled=True))
    act = store.get_or_create_document(
        conn, source_id="s", source_document_id="act",
        title="Sample Act", document_type="Act", jurisdiction="central")
    rule = store.get_or_create_document(
        conn, source_id="s", source_document_id="rule",
        title="Sample Rule", document_type="Rule", jurisdiction="state")
    for index, doc in enumerate((act, rule), start=1):
        ver = store.create_version(
            conn, document_id=doc, content_sha256=f"{index:064d}",
            raw_storage_path=None, extracted_text_path=None,
            extraction_method="text", extraction_status="ok",
            parser_warnings=[])
        store.create_report(
            conn, document_id=doc, old_version_id=None, new_version_id=ver,
            change_type="new_document", summary="S", claims=[])
        if index == 2:
            conn.execute(
                "UPDATE change_reports SET verification_status='approved' "
                "WHERE id=(SELECT MAX(id) FROM change_reports)")
    conn.commit()
    return conn, act, rule


def test_list_documents_filters(tmp_path):
    conn, act, rule = _seed_two_documents(tmp_path / "t.db")
    try:
        assert {r["id"] for r in store.list_documents(conn)} == {act, rule}
        assert [r["id"] for r in store.list_documents(
            conn, doc_type="Act")] == [act]
        assert [r["id"] for r in store.list_documents(
            conn, jurisdiction="state")] == [rule]
        assert [r["id"] for r in store.list_documents(
            conn, doc_type="Act", jurisdiction="state")] == []
        assert [r["id"] for r in store.list_documents(
            conn, source="nope")] == []
    finally:
        conn.close()


def test_list_reports_filters(tmp_path):
    conn, act, rule = _seed_two_documents(tmp_path / "t.db")
    try:
        approved = store.list_reports_filtered(conn, verification="approved")
        assert len(approved) == 1
        assert approved[0]["document_id"] == rule
        by_type = store.list_reports_filtered(conn, change_type="new_document")
        assert len(by_type) == 2
        by_doc = store.list_reports_filtered(conn, document_id=act)
        assert len(by_doc) == 1 and by_doc[0]["document_id"] == act
        # Stamps are ISO strings, so "since" compares lexicographically.
        future = store.list_reports_filtered(
            conn, since="2999-01-01T00:00:00.000Z")
        assert future == []
        past = store.list_reports_filtered(
            conn, since="2000-01-01T00:00:00.000Z")
        assert len(past) == 2
    finally:
        conn.close()
