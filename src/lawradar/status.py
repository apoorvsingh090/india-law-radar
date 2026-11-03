"""Operator status snapshot (Milestone 14).

One read-only call answers "is this deployment healthy and what needs a
human right now?" without network access: source health, document and
report counts, pending review work, unexported approved reports, webhook
failures, the newest verified backup, and the last ingestion run.

The snapshot is informational; ``lawradar health`` keeps its exit-code
contract for start-up checks and ``lawradar sources health`` for sweep
alerting. Nothing here mutates the database.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from lawradar import __version__
from lawradar.db import store
from lawradar.ingestion import health


def _db_path(config) -> Path:
    prefix = "sqlite:///"
    text = str(config.db_url)
    if not text.startswith(prefix):
        raise ValueError("status supports sqlite db_url only")
    return Path(text[len(prefix):])


def _count(conn, sql: str, params: tuple = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _latest_backup(data_dir: str) -> dict | None:
    folder = Path(data_dir) / "backups"
    if not folder.is_dir():
        return None
    candidates = sorted(folder.glob("*.db"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None
    newest = candidates[-1]
    try:
        size = newest.stat().st_size
    except OSError:
        return None
    return {
        "name": newest.name,
        "path": str(newest),
        "bytes": size,
        "verified_sidecar": (folder / f"{newest.name}.sha256").is_file(),
    }


def collect_status(conn, config, *, now: datetime | None = None) -> dict:
    """Build the operator snapshot from local state only."""
    moment = now if now is not None else datetime.now(UTC)
    db_path = _db_path(config)

    source_rows = [dict(row) for row in store.list_sources(conn)]
    health_items = health.evaluate_sources(source_rows, moment)
    source_summary = health.summarize(health_items, moment)
    by_status: dict[str, int] = {}
    for item in health_items:
        by_status[item.status] = by_status.get(item.status, 0) + 1

    review_counts = store.count_review_tasks_by_status(conn)
    reports_total = store.count_reports(conn)
    approved_unexported = _count(
        conn,
        """SELECT COUNT(*) FROM change_reports r
           WHERE r.verification_status='approved'
             AND NOT EXISTS (
               SELECT 1 FROM evidence_bundles b
               WHERE b.change_report_id=r.id)""",
    )
    failed_attempts = store.count_failed_attempts(conn)
    targets = list(getattr(config, "notify_webhooks", []) or [])
    enabled = bool(getattr(config, "notify_enabled", False))

    runs = store.latest_runs(conn, 1)
    last_run = dict(runs[0]) if runs else None

    try:
        db_bytes = db_path.stat().st_size
    except OSError:
        db_bytes = 0

    applied = store.applied_migrations(conn)
    pending = store.pending_migrations(conn)

    snapshot = {
        "generated_at": health.format_utc(moment),
        "app": {
            "version": __version__,
            "db_path": str(db_path),
            "db_bytes": db_bytes,
            "migrations": len(applied),
            "pending_migrations": pending,
        },
        "sources": {
            "monitored": source_summary["monitored"],
            "healthy": source_summary["healthy"],
            "stale": source_summary["stale"],
            "failing": source_summary["failing"],
            "disabled": by_status.get("disabled", 0),
            "manual": by_status.get("manual", 0),
            "retired": by_status.get("retired", 0),
        },
        "documents": {
            "documents": _count(conn, "SELECT COUNT(*) FROM documents"),
            "versions": _count(conn, "SELECT COUNT(*) FROM document_versions"),
        },
        "reports": {
            "total": reports_total,
            "pending_review": review_counts.get("pending", 0),
            "approved": review_counts.get("approved", 0),
            "rejected": review_counts.get("rejected", 0),
            "needs_changes": review_counts.get("needs_changes", 0),
            "approved_without_bundle": approved_unexported,
        },
        "notifications": {
            "enabled": enabled,
            "targets": len(targets),
            "failed_attempts": failed_attempts,
        },
        "backup": _latest_backup(config.data_dir),
        "last_run": last_run,
    }

    attention: list[str] = []
    if pending:
        attention.append(f"database schema is behind: {len(pending)} "
                         "migration(s) pending - run `lawradar init`")
    for item in health_items:
        if item.status in ("stale", "failing"):
            attention.append(f"source '{item.source_id}' is {item.status}: "
                             f"{item.detail}")
    if review_counts.get("pending", 0):
        attention.append(f"{review_counts['pending']} report(s) awaiting "
                         "review: lawradar review --list")
    if failed_attempts:
        attention.append(f"{failed_attempts} failed webhook attempt(s): "
                         "lawradar notify send")
    if approved_unexported:
        attention.append(f"{approved_unexported} approved report(s) have no "
                         "evidence bundle: lawradar bundles create <id>")
    snapshot["attention"] = attention
    return snapshot


def format_status(snapshot: dict) -> str:
    """Compact operator one-pager (ASCII-friendly, stable order)."""
    app = snapshot["app"]
    sources = snapshot["sources"]
    docs = snapshot["documents"]
    reports = snapshot["reports"]
    notify = snapshot["notifications"]
    ok_count = (sources["monitored"] - sources["stale"]
                - sources["failing"])
    source_line = (
        f"sources: {sources['monitored']} monitored "
        f"(ok={ok_count} stale={sources['stale']} "
        f"failing={sources['failing']}) | "
        f"disabled={sources['disabled']} manual={sources['manual']} "
        f"retired={sources['retired']}")
    report_line = (
        f"reports: {reports['total']} total | "
        f"pending={reports['pending_review']} "
        f"approved={reports['approved']} rejected={reports['rejected']} "
        f"needs_changes={reports['needs_changes']} | "
        f"approved without bundle={reports['approved_without_bundle']}")
    notify_line = (
        f"notifications: {'enabled' if notify['enabled'] else 'disabled'} "
        f"({notify['targets']} targets) | "
        f"failed attempts={notify['failed_attempts']}")
    header_line = (f"India Law Radar v{app['version']} - generated "
                   f"{snapshot['generated_at']}")
    pending = app["pending_migrations"]
    pending_note = (f"; {len(pending)} pending - run `lawradar init`"
                    if pending else "")
    db_line = (f"db: {app['db_path']} ({app['db_bytes']} bytes, "
               f"{app['migrations']} migrations{pending_note})")
    lines = [
        header_line,
        db_line,
        source_line,
        f"documents: {docs['documents']} ({docs['versions']} versions)",
        report_line,
        notify_line,
    ]
    run = snapshot["last_run"]
    if run:
        lines.append(
            f"last run: {run['id']} {run['source_id']} {run['status']} "
            f"changed={run['documents_changed']} "
            f"at {run['started_at']}")
    else:
        lines.append("last run: (none)")
    backup = snapshot["backup"]
    if backup:
        sidecar = "" if backup["verified_sidecar"] else " (sidecar missing)"
        lines.append(f"backup: {backup['name']} ({backup['bytes']} bytes)"
                     f"{sidecar}")
    else:
        lines.append("backup: (none found)")
    attention = snapshot["attention"]
    if attention:
        lines.append("attention:")
        lines.extend(f"  - {item}" for item in attention)
    else:
        lines.append("attention: none")
    return "\n".join(lines)
