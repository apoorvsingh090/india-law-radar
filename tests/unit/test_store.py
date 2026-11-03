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
