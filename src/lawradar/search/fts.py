"""Full-text search (Milestone 5): FTS5 with LIKE fallback.

The pipeline indexes every version's extracted text; ``reindex`` rebuilds
from the text files on disk. Queries prefer FTS5 (snippets + ranking) and
fall back to LIKE when FTS5 is unavailable or the query is not valid
FTS5 syntax. User input is never interpolated into SQL raw.
"""
from __future__ import annotations

from pathlib import Path

_FTS_OK: bool | None = None


def fts_available(conn) -> bool:
    """True when the connected database supports FTS5 queries."""
    global _FTS_OK
    if _FTS_OK is not None:
        return _FTS_OK
    try:
        conn.execute("SELECT count(*) FROM search_fts WHERE search_fts MATCH 'x'").fetchone()
        _FTS_OK = True
    except Exception:  # noqa: BLE001 — missing table/module means no FTS
        _FTS_OK = False
    return _FTS_OK


def reset_cache() -> None:  # test helper
    global _FTS_OK
    _FTS_OK = None


def _safe_match(query: str) -> str:
    """Quote FTS5 special characters so user input is treated literally."""
    cleaned = " ".join(query.split())
    return '"' + cleaned.replace('"', '""') + '"'


def upsert_index(conn, *, doc_id: int, version_id: int, title: str,
                 body: str) -> None:
    conn.execute(
        """INSERT INTO search_index (doc_id, version_id, title, body)
           VALUES (?, ?, ?, ?)
           ON CONFLICT (version_id) DO UPDATE SET
             doc_id=excluded.doc_id, title=excluded.title, body=excluded.body""",
        (doc_id, version_id, title, body or ""),
    )


def index_version(conn, *, doc_id: int, version_id: int, title: str,
                  text_path: str | None) -> None:
    body = ""
    if text_path:
        try:
            body = Path(text_path).read_text(encoding="utf-8")
        except OSError:
            body = ""
    upsert_index(conn, doc_id=doc_id, version_id=version_id, title=title,
                 body=body)


def reindex(conn) -> int:
    """Rebuild the whole index from stored text files. Returns row count."""
    conn.execute("DELETE FROM search_index")
    rows = conn.execute(
        "SELECT v.id AS vid, v.document_id AS did, d.title AS title, "
        "v.extracted_text_path AS path FROM document_versions v "
        "JOIN documents d ON d.id=v.document_id").fetchall()
    count = 0
    for row in rows:
        index_version(conn, doc_id=row["did"], version_id=row["vid"],
                      title=row["title"], text_path=row["path"])
        count += 1
    conn.commit()
    return count


def ensure_indexed(conn) -> int:
    """Index anything missing (e.g. databases built before M5)."""
    have = conn.execute("SELECT COUNT(*) AS c FROM search_index").fetchone()
    versions = conn.execute(
        "SELECT COUNT(*) AS c FROM document_versions").fetchone()
    if int(have["c"]) >= int(versions["c"]):
        return 0
    return reindex(conn)


def search(conn, query: str, limit: int = 20) -> list[dict]:
    """Search titles + extracted text. Returns dicts with snippets."""
    query = (query or "").strip()
    if not query:
        return []
    if fts_available(conn):
        try:
            rows = conn.execute(
                "SELECT s.doc_id AS id, s.title AS title, "
                "snippet(search_fts, 1, '<b>', '</b>', ' … ', 12) AS snippet "
                "FROM search_fts JOIN search_index s "
                "ON s.rowid = search_fts.rowid "
                "WHERE search_fts MATCH ? ORDER BY rank LIMIT ?",
                (_safe_match(query), limit)).fetchall()
            return [{"id": r["id"], "title": r["title"],
                     "snippet": r["snippet"], "engine": "fts"}
                    for r in rows]
        except Exception:  # noqa: BLE001 — bad MATCH syntax falls back
            pass
    like = f"%{query}%"
    rows = conn.execute(
        "SELECT d.id AS id, d.title AS title, "
        "substr(s.body, 1, 200) AS snippet FROM documents d "
        "LEFT JOIN search_index s ON s.doc_id=d.id "
        "WHERE d.title LIKE ? OR d.source_document_id LIKE ? "
        "OR d.issuing_authority LIKE ? OR s.body LIKE ? "
        "GROUP BY d.id ORDER BY d.updated_at DESC LIMIT ?",
        (like, like, like, like, limit)).fetchall()
    return [{"id": r["id"], "title": r["title"],
             "snippet": (r["snippet"] or "")[:200], "engine": "like"}
            for r in rows]
