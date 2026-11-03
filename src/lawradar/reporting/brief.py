"""Publishable Markdown briefs for approved change reports (Milestone 15).

The evidence bundle (M12) is the verifiable artifact; the brief is the
readable one - a single Markdown page a human can forward to a client
or paste into a memo. It renders only from stored rows (report,
document, versions, citations, review history) and refuses anything a
human has not approved. Claims show the same ``c1..cN`` labels the
report stores; citations are listed in insertion order, which is the
order those labels were assigned when the report was generated.
"""
from __future__ import annotations

import json

from lawradar import __version__
from lawradar.db import store
from lawradar.review.queue import audit_trail

NOT_ADVICE = ("Human-reviewed publication produced from stored evidence; "
              "it is not legal advice.")


class BriefError(Exception):
    """Raised when a brief cannot be rendered from stored data."""


class BriefRefused(Exception):
    """Raised when the report is not approved for publication."""


def _version_row(conn, version_id: int | None) -> dict:
    if not version_id:
        return {}
    row = conn.execute(
        "SELECT * FROM document_versions WHERE id=?", (version_id,)
    ).fetchone()
    return dict(row) if row else {}


def _approved_task(trail: list[dict]) -> dict:
    approved = [task for task in trail if task.get("status") == "approved"]
    return approved[-1] if approved else {}


def _quote_block(text: str, prefix: str = "    > ") -> list[str]:
    clean = " ".join((text or "").split())
    if not clean:
        return []
    return [f"{prefix}{clean}"]


def build_brief(conn, report_id: int, *, generated_at: str) -> str:
    """Render one approved report as deterministic Markdown."""
    report_row = store.get_report(conn, report_id)
    if report_row is None:
        raise BriefError(f"unknown report id {report_id}")
    report = dict(report_row)
    if report["verification_status"] != "approved":
        raise BriefRefused(
            f"report {report_id} is not approved yet "
            f"(status: {report['verification_status']}); "
            "approve it via `lawradar review --approve` before sharing")

    document_row = store.get_document(conn, report["document_id"])
    document = dict(document_row) if document_row else {}
    new_version = _version_row(conn, report["new_version_id"])
    old_version = _version_row(conn, report["old_version_id"])
    citations = [dict(c) for c in store.list_citations(conn, report_id)]
    claims = json.loads(report["claims_json"] or "[]")
    affected = json.loads(report["affected_sections"] or "[]")
    trail = audit_trail(conn, report_id)
    task = _approved_task(trail)

    title = document.get("title") or "(untitled document)"
    lines = [
        f"# {title}",
        "",
        f"**Change report #{report_id}** - {report['change_type']}",
        f"**Status:** approved ({report['published_at'] or 'stored'})",
        f"**Generated:** {generated_at}",
        f"**Issuing authority:** {document.get('issuing_authority') or 'unknown'}",
        f"**Jurisdiction:** {document.get('jurisdiction') or 'unknown'}",
        f"**Official URL:** {document.get('official_url') or '(not recorded)'}",
        "",
        "## Summary",
        "",
        report["summary"] or "(no summary recorded)",
        "",
        "## Affected sections",
        "",
    ]
    if affected:
        lines.extend(f"- {item}" for item in affected)
    else:
        lines.append("- (none recorded)")
    lines.extend([
        "",
        "## Evidence",
        "",
    ])
    lines.append(
        f"Version {new_version.get('version_number', '?')}: "
        f"sha256 `{str(new_version.get('content_sha256') or '')[:16]}` "
        f"retrieved {new_version.get('retrieved_at') or 'unknown'}, "
        f"extraction {new_version.get('extraction_status') or 'unknown'}")
    if old_version:
        lines.append(
            f"Previous version {old_version.get('version_number', '?')}: "
            f"sha256 `{str(old_version.get('content_sha256') or '')[:16]}` "
            f"retrieved {old_version.get('retrieved_at') or 'unknown'}")
    else:
        lines.append("Previous version: none (first captured version)")
    lines.extend(["", "## Claims", ""])
    if claims:
        for claim in claims:
            ids = ", ".join(claim.get("citation_ids") or []) or "none"
            lines.append(
                f"- [{claim.get('claim_type') or 'claim'}] "
                f"{claim.get('claim') or ''} (citations: {ids})")
    else:
        lines.append("- (no claims recorded)")
    lines.extend(["", "## Citation evidence", ""])
    if citations:
        for index, citation in enumerate(citations, start=1):
            lines.append(
                f"### c{index} - {citation['locator_type'] or 'locator'}")
            lines.append("")
            lines.append(f"- Locator: {citation['locator_value'] or '(none)'}")
            lines.extend(_quote_block(citation["quoted_text"]))
            lines.append(
                f"- Source URL: {citation['source_url'] or '(none)'}")
            lines.append(
                f"- Verification: {citation['verification_status']}")
            lines.append("")
    else:
        lines.extend(["- (no citations recorded)", ""])
    lines.extend(["## Human review", ""])
    if task:
        lines.append(
            f"- {task.get('reviewer') or 'unknown reviewer'} approved on "
            f"{task.get('resolved_at') or 'an unrecorded time'}")
        note = " ".join((task.get("review_notes") or "").split())
        if note:
            lines.append(f"- Notes: {note}")
        lines.append(f"- Queue reason: {task.get('reason') or '(none)'}")
    else:
        lines.append("- (no approved review task recorded)")
    if report.get("reviewer_notes"):
        note = " ".join(report["reviewer_notes"].split())
        lines.append(f"- Publication notes: {note}")
    lines.extend([
        "",
        "## Reproduction",
        "",
        f"- `lawradar reports show {report_id}`",
        f"- `lawradar reports verify {report_id}`",
        f"- `lawradar bundles create {report_id}` (offline-verifiable export)",
        "",
        "---",
        "",
        NOT_ADVICE,
        f"Rendered by India Law Radar v{__version__} from stored evidence only.",
        "",
    ])
    return "\n".join(lines)
