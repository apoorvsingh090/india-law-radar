"""SQLite repository layer: single implementation, local file DB.

Owns schema migrations (``migrations/*.sql`` applied in order) and all
CRUD for sources, documents, versions, and ingestion runs. Postgres can
replace this module in deployment; callers only use these functions.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _applied(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL "
        "DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
    )
    return {row["name"] for row in conn.execute("SELECT name FROM _migrations")}


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply pending ``migrations/*.sql`` in filename order. Returns applied."""
    done = _applied(conn)
    applied: list[str] = []
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name in done:
            continue
        with sql_file.open("r", encoding="utf-8") as fh:
            conn.executescript(fh.read())
        conn.execute("INSERT INTO _migrations (name) VALUES (?)", (sql_file.name,))
        conn.commit()
        applied.append(sql_file.name)
    return applied


def init_db(db_path: str | Path) -> list[str]:
    """Create/open the DB and apply migrations. Returns newly applied names."""
    conn = connect(db_path)
    try:
        return apply_migrations(conn)
    finally:
        conn.close()


# -- sources ---------------------------------------------------------------

def upsert_source(conn: sqlite3.Connection, record) -> None:
    """Insert or update a source registry entry (by id)."""
    conn.execute(
        """INSERT INTO sources
           (id, name, base_url, source_type, jurisdiction, access_method,
            terms_review_status, poll_interval_minutes, enabled, coverage_notes,
            updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
           ON CONFLICT (id) DO UPDATE SET
             name=excluded.name, base_url=excluded.base_url,
             source_type=excluded.source_type, jurisdiction=excluded.jurisdiction,
             access_method=excluded.access_method,
             terms_review_status=excluded.terms_review_status,
             poll_interval_minutes=excluded.poll_interval_minutes,
             enabled=excluded.enabled, coverage_notes=excluded.coverage_notes,
             updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (
            record.id, record.name, record.base_url, record.source_type,
            record.jurisdiction, record.access_method,
            record.terms_review_status, record.poll_interval_minutes,
            1 if record.enabled else 0, record.coverage_notes,
        ),
    )


def list_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM sources ORDER BY id"))


def get_source(conn: sqlite3.Connection, source_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sources WHERE id = ?",
                        (source_id,)).fetchone()


def record_source_check(
    conn: sqlite3.Connection, source_id: str, success: bool, error: str = ""
) -> None:
    """Update last-check timestamps. Failures never record a success."""
    if success:
        conn.execute(
            """UPDATE sources SET last_checked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               last_success_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               last_error='', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE id=?""",
            (source_id,),
        )
    else:
        conn.execute(
            """UPDATE sources SET last_checked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               last_error=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE id=?""",
            (error[:2000], source_id),
        )


# -- documents + versions ---------------------------------------------------

def get_or_create_document(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    source_document_id: str,
    title: str,
    document_type: str = "unknown",
    issuing_authority: str = "",
    jurisdiction: str = "unknown",
    official_url: str = "",
    language: str = "en",
) -> int:
    conn.execute(
        """INSERT INTO documents
           (source_id, source_document_id, title, document_type,
            issuing_authority, jurisdiction, official_url, language)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (source_id, source_document_id) DO UPDATE SET
             title=excluded.title, document_type=excluded.document_type,
             issuing_authority=excluded.issuing_authority,
             jurisdiction=excluded.jurisdiction, official_url=excluded.official_url,
             language=excluded.language,
             updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (source_id, source_document_id, title, document_type,
         issuing_authority, jurisdiction, official_url, language),
    )
    row = conn.execute(
        "SELECT id FROM documents WHERE source_id=? AND source_document_id=?",
        (source_id, source_document_id),
    ).fetchone()
    return int(row["id"])


def version_exists(conn: sqlite3.Connection, document_id: int, sha: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM document_versions WHERE document_id=? AND content_sha256=?",
            (document_id, sha),
        ).fetchone()
        is not None
    )


def latest_version(conn: sqlite3.Connection,
                   document_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM document_versions WHERE document_id=? "
        "ORDER BY version_number DESC LIMIT 1",
        (document_id,),
    ).fetchone()


def next_version_number(conn: sqlite3.Connection, document_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) AS m FROM document_versions "
        "WHERE document_id=?",
        (document_id,),
    ).fetchone()
    return int(row["m"]) + 1


def create_version(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    content_sha256: str,
    raw_storage_path: str | None,
    extracted_text_path: str | None,
    extraction_method: str,
    extraction_status: str,
    parser_warnings: list[str],
    review_status: str = "pending",
) -> int:
    number = next_version_number(conn, document_id)
    cursor = conn.execute(
        """INSERT INTO document_versions
           (document_id, version_number, content_sha256, raw_storage_path,
            extracted_text_path, extraction_method, extraction_status,
            parser_warnings, review_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (document_id, number, content_sha256, raw_storage_path,
         extracted_text_path, extraction_method, extraction_status,
         json.dumps(parser_warnings), review_status),
    )
    return int(cursor.lastrowid)


def count_versions(conn: sqlite3.Connection, document_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM document_versions WHERE document_id=?",
        (document_id,),
    ).fetchone()
    return int(row["c"])


def list_versions(conn: sqlite3.Connection,
                  document_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM document_versions WHERE document_id=? "
            "ORDER BY version_number",
            (document_id,),
        )
    )


# -- documents queries ------------------------------------------------------

def list_documents(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM document_versions v "
            "WHERE v.document_id=d.id) AS versions FROM documents d "
            "ORDER BY d.updated_at DESC LIMIT ?",
            (limit,),
        )
    )


def get_document(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id=?",
                        (document_id,)).fetchone()


def search_documents(conn: sqlite3.Connection, query: str,
                     limit: int = 20) -> list[sqlite3.Row]:
    like = f"%{query}%"
    return list(
        conn.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM document_versions v "
            "WHERE v.document_id=d.id) AS versions FROM documents d "
            "WHERE d.title LIKE ? OR d.source_document_id LIKE ? "
            "OR d.issuing_authority LIKE ? ORDER BY d.updated_at DESC LIMIT ?",
            (like, like, like, limit),
        )
    )


# -- ingestion runs ----------------------------------------------------------

def create_run(conn: sqlite3.Connection, source_id: str) -> int:
    cursor = conn.execute(
        "INSERT INTO ingestion_runs (source_id, status) VALUES (?, 'running')",
        (source_id,),
    )
    return int(cursor.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    discovered: int = 0,
    downloaded: int = 0,
    changed: int = 0,
    failed: int = 0,
    error_summary: str = "",
) -> None:
    conn.execute(
        """UPDATE ingestion_runs SET finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
           status=?, documents_discovered=?, documents_downloaded=?,
           documents_changed=?, documents_failed=?, error_summary=?
           WHERE id=?""",
        (status, discovered, downloaded, changed, failed,
         error_summary[:4000], run_id),
    )


def latest_runs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return list(
        conn.execute("SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT ?",
                     (limit,))
    )
