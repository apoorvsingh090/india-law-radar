"""Review queue + audit trail (Milestone 4).

Policy (default ``manual``): every report starts ``pending``/unpublished.
Only an explicit human ``review --approve`` sets ``published_at``.
Rejections and change-requests require reviewer notes. All actions append
to ``review_tasks`` — the audit trail is never overwritten, only resolved.
"""
from __future__ import annotations

from lawradar.db import store

DECISIONS = {"approved", "rejected", "needs_changes"}
NEEDS_NOTES = {"rejected", "needs_changes"}


class ReviewError(ValueError):
    """Raised for invalid review actions."""


def open_tasks_for_report(conn, report_id: int) -> list:
    """Pending review tasks for one report (usually zero or one)."""
    return [t for t in store.list_review_tasks(conn, status="pending")
            if t["change_report_id"] == report_id]


def ensure_task(conn, *, report_id: int, document_version_id: int | None,
                reason: str, severity: str = "medium") -> int:
    """Open a task unless an identical pending one exists. Returns task id."""
    for task in open_tasks_for_report(conn, report_id):
        if task["reason"] == reason:
            return int(task["id"])
    return store.create_review_task(
        conn, document_version_id=document_version_id,
        change_report_id=report_id, reason=reason, severity=severity)


def auto_queue(conn, *, report_id: int, change_type: str,
               new_version_id: int, extraction_status: str) -> list[int]:
    """Queue human review for uncertain or high-impact reports."""
    created: list[int] = []
    if change_type == "unknown" or extraction_status != "ok":
        created.append(ensure_task(
            conn, report_id=report_id, document_version_id=new_version_id,
            reason=("unreadable extraction evidence; verify against the "
                    "official source before use"),
            severity="high"))
    elif change_type in ("possible_amendment", "corrigendum"):
        created.append(ensure_task(
            conn, report_id=report_id, document_version_id=new_version_id,
            reason=(f"change classified as {change_type}; confirm the legal "
                    "effect with the official source"),
            severity="medium"))
    return created


def resolve(conn, *, report_id: int, decision: str, reviewer: str = "",
            notes: str = "") -> dict:
    """Apply a human decision. Returns a summary dict. Raises ReviewError."""
    if decision not in DECISIONS:
        raise ReviewError(
            f"unknown decision {decision!r} (expected one of {sorted(DECISIONS)})")
    if decision in NEEDS_NOTES and not notes.strip():
        raise ReviewError(
            f"reviewer notes are required when {decision.replace('_', ' ')}")
    report = store.get_report(conn, report_id)
    if report is None:
        raise ReviewError(f"unknown report id {report_id}")
    tasks = open_tasks_for_report(conn, report_id)
    if not tasks:
        # Record the decision itself so the trail is complete even when
        # auto-queue created nothing (e.g. a clean text_modified report).
        task_id = store.create_review_task(
            conn, document_version_id=report["new_version_id"],
            change_report_id=report_id,
            reason=f"manual {decision} without auto-queued task",
            severity="low")
        tasks = [store.get_review_task(conn, task_id)]
    reviewer = reviewer.strip() or "local"
    for task in tasks:
        store.resolve_review_task(
            conn, task["id"], status=decision, reviewer=reviewer,
            review_notes=notes.strip())
    if decision == "approved":
        store.publish_report(conn, report_id, reviewer_notes=notes.strip())
        verification = "approved"
    elif decision == "rejected":
        store.unpublish_report(conn, report_id, "rejected",
                               reviewer_notes=notes.strip())
        verification = "rejected"
    else:
        store.unpublish_report(conn, report_id, "needs_changes",
                               reviewer_notes=notes.strip())
        verification = "needs_changes"
    conn.commit()
    return {"report_id": report_id, "decision": decision,
            "verification": verification, "reviewer": reviewer,
            "tasks_resolved": len(tasks)}


def audit_trail(conn, report_id: int) -> list[dict]:
    """Full review history for a report, oldest first (audit trail)."""
    tasks = [dict(t) for t in store.list_review_tasks(conn)
             if t["change_report_id"] == report_id]
    tasks.sort(key=lambda t: t["id"])
    return tasks


def queue_summary(conn) -> dict:
    """Counts for dashboard/CLI display."""
    counts = store.count_review_tasks_by_status(conn)
    return {"pending": counts.get("pending", 0),
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "needs_changes": counts.get("needs_changes", 0),
            "total": sum(counts.values())}
