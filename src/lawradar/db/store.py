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
             retired_at=NULL,
             updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
        (
            record.id, record.name, record.base_url, record.source_type,
            record.jurisdiction, record.access_method,
            record.terms_review_status, record.poll_interval_minutes,
            1 if record.enabled else 0, record.coverage_notes,
        ),
    )


def retire_missing_sources(conn: sqlite3.Connection,
                           active_ids: set[str]) -> int:
    """Soft-retire DB sources no longer present in the loaded registry."""
    if active_ids:
        placeholders = ",".join("?" for _ in active_ids)
        cursor = conn.execute(
            f"""UPDATE sources SET retired_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE retired_at IS NULL AND id NOT IN ({placeholders})""",
            tuple(sorted(active_ids)),
        )
    else:
        cursor = conn.execute(
            """UPDATE sources SET retired_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE retired_at IS NULL""")
    return cursor.rowcount


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


# -- change reports + citations ------------------------------------------------

def find_report(
    conn: sqlite3.Connection,
    document_id: int,
    old_version_id: int | None,
    new_version_id: int,
) -> sqlite3.Row | None:
    if old_version_id is None:
        return conn.execute(
            "SELECT * FROM change_reports WHERE document_id=? "
            "AND old_version_id IS NULL AND new_version_id=?",
            (document_id, new_version_id),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM change_reports WHERE document_id=? "
        "AND old_version_id=? AND new_version_id=?",
        (document_id, old_version_id, new_version_id),
    ).fetchone()


def create_report(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    old_version_id: int | None,
    new_version_id: int,
    change_type: str,
    diff_text: str = "",
    summary: str = "",
    affected_sections: list | None = None,
    claims: list | None = None,
    verification_status: str = "unverified",
) -> int:
    cursor = conn.execute(
        """INSERT INTO change_reports
           (document_id, old_version_id, new_version_id, change_type,
            diff_text, summary, affected_sections, claims_json,
            verification_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (document_id, old_version_id, new_version_id, change_type, diff_text,
         summary, json.dumps(affected_sections or []),
         json.dumps(claims or []), verification_status),
    )
    return int(cursor.lastrowid)


def add_citation(
    conn: sqlite3.Connection,
    *,
    change_report_id: int,
    document_version_id: int,
    locator_type: str = "text span",
    locator_value: str = "",
    quoted_text: str = "",
    source_url: str = "",
    verification_status: str = "unverified",
) -> int:
    cursor = conn.execute(
        """INSERT INTO citations
           (change_report_id, document_version_id, locator_type,
            locator_value, quoted_text, source_url, verification_status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (change_report_id, document_version_id, locator_type, locator_value,
         quoted_text[:2000], source_url, verification_status),
    )
    return int(cursor.lastrowid)


def list_reports(
    conn: sqlite3.Connection, limit: int = 50, document_id: int | None = None
) -> list[sqlite3.Row]:
    if document_id is None:
        return list(conn.execute(
            "SELECT r.*, d.title AS document_title FROM change_reports r "
            "JOIN documents d ON d.id=r.document_id "
            "ORDER BY r.id DESC LIMIT ?", (limit,)))
    return list(conn.execute(
        "SELECT r.*, d.title AS document_title FROM change_reports r "
        "JOIN documents d ON d.id=r.document_id WHERE r.document_id=? "
        "ORDER BY r.id DESC LIMIT ?", (document_id, limit)))


def get_report(conn: sqlite3.Connection, report_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT r.*, d.title AS document_title FROM change_reports r "
        "JOIN documents d ON d.id=r.document_id WHERE r.id=?",
        (report_id,)).fetchone()


def list_published_reports(
    conn: sqlite3.Connection, limit: int = 50
) -> list[sqlite3.Row]:
    """Reports a human approved (published_at set), newest first.

    The only feed-visible set — ingestion can never add to it because
    publication happens exclusively in review approval.
    """
    return list(conn.execute(
        "SELECT r.*, d.title AS document_title FROM change_reports r "
        "JOIN documents d ON d.id=r.document_id "
        "WHERE r.published_at IS NOT NULL "
        "AND r.verification_status='approved' "
        "ORDER BY r.published_at DESC, r.id DESC LIMIT ?", (limit,)))


def list_reports_filtered(
    conn: sqlite3.Connection,
    *,
    source: str | None = None,
    jurisdiction: str | None = None,
    doc_type: str | None = None,
    verification: str | None = None,
    limit: int = 100,
) -> list[sqlite3.Row]:
    """Change-feed query with optional filters (web UI + API)."""
    clauses = []
    params: list = []
    if source:
        clauses.append("d.source_id = ?")
        params.append(source)
    if jurisdiction:
        clauses.append("d.jurisdiction = ?")
        params.append(jurisdiction)
    if doc_type:
        clauses.append("d.document_type = ?")
        params.append(doc_type)
    if verification:
        clauses.append("r.verification_status = ?")
        params.append(verification)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return list(conn.execute(
        "SELECT r.*, d.title AS document_title FROM change_reports r "
        f"JOIN documents d ON d.id=r.document_id {where} "
        "ORDER BY r.id DESC LIMIT ?", params))


def list_citations(conn: sqlite3.Connection,
                   report_id: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM citations WHERE change_report_id=? ORDER BY id",
        (report_id,)))


def count_reports(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM change_reports").fetchone()
    return int(row["c"])


# -- review tasks (audit trail) + publication --------------------------------

def create_review_task(
    conn: sqlite3.Connection,
    *,
    document_version_id: int | None,
    change_report_id: int | None,
    reason: str,
    severity: str = "medium",
) -> int:
    cursor = conn.execute(
        """INSERT INTO review_tasks
           (document_version_id, change_report_id, reason, severity)
           VALUES (?, ?, ?, ?)""",
        (document_version_id, change_report_id, reason, severity),
    )
    return int(cursor.lastrowid)


def get_review_task(conn: sqlite3.Connection,
                    task_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM review_tasks WHERE id=?",
                        (task_id,)).fetchone()


def list_review_tasks(
    conn: sqlite3.Connection, status: str | None = None, limit: int = 100
) -> list[sqlite3.Row]:
    if status is None:
        return list(conn.execute(
            "SELECT t.*, r.document_id AS document_id FROM review_tasks t "
            "LEFT JOIN change_reports r ON r.id=t.change_report_id "
            "ORDER BY t.id DESC LIMIT ?", (limit,)))
    return list(conn.execute(
        "SELECT t.*, r.document_id AS document_id FROM review_tasks t "
        "LEFT JOIN change_reports r ON r.id=t.change_report_id "
        "WHERE t.status=? ORDER BY t.id DESC LIMIT ?", (status, limit)))


def count_review_tasks_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    return {row["status"]: int(row["c"]) for row in conn.execute(
        "SELECT status, COUNT(*) AS c FROM review_tasks GROUP BY status")}


def resolve_review_task(
    conn: sqlite3.Connection, task_id: int, *, status: str, reviewer: str,
    review_notes: str = "",
) -> None:
    conn.execute(
        """UPDATE review_tasks SET status=?, reviewer=?, review_notes=?,
           resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
        (status, reviewer, review_notes[:4000], task_id),
    )


def set_report_verification(
    conn: sqlite3.Connection, report_id: int, verification: str,
    reviewer_notes: str = "",
) -> None:
    conn.execute(
        "UPDATE change_reports SET verification_status=?, reviewer_notes=? "
        "WHERE id=?",
        (verification, reviewer_notes[:4000], report_id),
    )


def publish_report(
    conn: sqlite3.Connection, report_id: int, reviewer_notes: str = ""
) -> None:
    """Mark a report published. Only called from an approved human review."""
    conn.execute(
        """UPDATE change_reports SET verification_status='approved',
           reviewer_notes=?,
           published_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
        (reviewer_notes[:4000], report_id),
    )


def unpublish_report(
    conn: sqlite3.Connection, report_id: int, verification: str,
    reviewer_notes: str = "",
) -> None:
    """Reverse a publication after a later non-approved review decision."""
    conn.execute(
        """UPDATE change_reports SET verification_status=?, reviewer_notes=?,
           published_at=NULL WHERE id=?""",
        (verification, reviewer_notes[:4000], report_id),
    )


def set_citation_verification(
    conn: sqlite3.Connection, citation_id: int, verification: str
) -> None:
    conn.execute(
        "UPDATE citations SET verification_status=? WHERE id=?",
        (verification, citation_id),
    )


def set_ai_attempts(
    conn: sqlite3.Connection, report_id: int, attempts: list
) -> None:
    conn.execute(
        "UPDATE change_reports SET ai_attempts=? WHERE id=?",
        (json.dumps(attempts), report_id),
    )


# -- user feedback (M7) ------------------------------------------------------

def add_feedback(
    conn: sqlite3.Connection, *, change_report_id: int | None, contact: str,
    message: str,
) -> int:
    message = (message or "").strip()
    if not message:
        raise ValueError("feedback message must not be empty")
    if len(message) > 4000:
        raise ValueError("feedback message too long (max 4000 characters)")
    cursor = conn.execute(
        "INSERT INTO feedback (change_report_id, contact, message) "
        "VALUES (?, ?, ?)",
        (change_report_id, (contact or "").strip()[:200], message),
    )
    return int(cursor.lastrowid)


def list_feedback(
    conn: sqlite3.Connection, status: str | None = None, limit: int = 100
) -> list[sqlite3.Row]:
    if status is None:
        return list(conn.execute(
            "SELECT * FROM feedback ORDER BY id DESC LIMIT ?", (limit,)))
    return list(conn.execute(
        "SELECT * FROM feedback WHERE status=? ORDER BY id DESC LIMIT ?",
        (status, limit)))


def resolve_feedback(conn: sqlite3.Connection, feedback_id: int) -> None:
    cursor = conn.execute(
        "UPDATE feedback SET status='resolved', "
        "resolved_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
        (feedback_id,))
    if cursor.rowcount == 0:
        raise ValueError(f"unknown feedback id {feedback_id}")


def update_report_summary(
    conn: sqlite3.Connection,
    report_id: int,
    *,
    summary: str,
    claims: list,
    ai_attempts: list,
) -> None:
    """Persist an applied re-summarisation.

    Attempt history (including the model's own warnings) lives in
    ``ai_attempts``; human ``reviewer_notes`` are never overwritten here.
    """
    conn.execute(
        "UPDATE change_reports SET summary=?, claims_json=?, ai_attempts=? "
        "WHERE id=?",
        (summary, json.dumps(claims), json.dumps(ai_attempts), report_id),
    )
