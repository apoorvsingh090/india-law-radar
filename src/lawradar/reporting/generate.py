"""Deterministic report generation (Milestone 3). No LLM required.

Every report is built from stored versions + the deterministic diff only.
Summaries are labelled drafts, commencement is unverified unless evidenced
(which M3 never claims), and each claim carries citation ids persisted to
the ``citations`` table.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from lawradar.db import store
from lawradar.diffing.compare import DiffResult, classify_change, compute_diff
from lawradar.reporting.schema import validate_report

DRAFT_DISCLAIMER = "Draft explanation, not yet a legal conclusion."


def _read_version_text(row) -> str:
    path = (row or {}).get("extracted_text_path") if isinstance(row, dict) else row[
        "extracted_text_path"]
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _row_to_dict(row) -> dict:
    return dict(row) if row is not None else {}


def build_report(
    document: dict,
    old_version: dict | None,
    new_version: dict,
    old_text: str,
    new_text: str,
) -> dict:
    """Build (but do not persist) a change report. Always validated."""
    old_ok = bool(old_version) and old_version.get("extraction_status") == "ok"
    new_ok = new_version.get("extraction_status") == "ok"
    is_first = old_version is None
    diff: DiffResult | None = None
    if not is_first:
        diff = compute_diff(old_text, new_text)
    change_type = classify_change(
        is_first_version=is_first,
        old_extraction_ok=old_ok or is_first,
        new_extraction_ok=new_ok,
        diff=diff,
    )
    warnings: list[str] = []
    if not new_ok:
        warnings.append(
            "latest extraction is "
            f"{new_version.get('extraction_status')}; textual comparison "
            "withheld pending review"
        )
    if not is_first and not old_ok:
        warnings.append("previous extraction unreadable; comparison withheld")

    citations: list[dict] = []
    claims: list[dict] = []
    textual_changes: list[dict] = []

    def _cite(locator_type: str, locator_value: str, quoted: str,
              url: str) -> str:
        cid = f"c{len(citations) + 1}"
        citations.append({
            "citation_id": cid,
            "locator_type": locator_type,
            "locator_value": locator_value,
            "quoted_text": quoted[:500],
            "source_url": url,
            "verification_status": "unverified",
        })
        return cid

    url = document.get("official_url", "")
    source_cid = _cite("URL", url or "(no official URL recorded)",
                       document.get("title", ""), url)
    version_cid = _cite(
        "text span",
        f"version {new_version.get('version_number')} "
        f"sha256:{(new_version.get('content_sha256') or '')[:16]}…",
        (new_text[:200] if new_ok else "(extraction unavailable)"), url,
    )
    claims.append({
        "claim": f"Document titled {document.get('title', '')!r} is stored "
                 f"as version {new_version.get('version_number')} from "
                 f"{document.get('issuing_authority', '') or 'an unknown authority'}.",
        "claim_type": "source_fact",
        "citation_ids": [source_cid, version_cid],
        "verification_status": "unverified",
    })
    if is_first:
        summary = (
            f"{DRAFT_DISCLAIMER} First captured version "
            f"(v{new_version.get('version_number')}) of "
            f"{document.get('title', '')!r}; no prior text to compare."
        )
    elif diff is not None and not diff.identical and new_ok and old_ok:
        for change in diff.changes:
            cid = _cite("text span", change.source_locator,
                        change.new_text or change.old_text, url)
            textual_changes.append({
                "description": change.description,
                "old_text": change.old_text,
                "new_text": change.new_text,
                "source_locator": change.source_locator,
                "confidence": change.confidence,
            })
            claims.append({
                "claim": f"Observed change: {change.description}.",
                "claim_type": "textual_comparison",
                "citation_ids": [cid],
                "verification_status": "unverified",
            })
        sections = ", ".join(diff.affected_sections) or "unlabelled passages"
        summary = (
            f"{DRAFT_DISCLAIMER} Compared "
            f"v{old_version.get('version_number')}->v{new_version.get('version_number')}: "
            f"{diff.lines_added} line(s) added, {diff.lines_removed} removed, "
            f"affecting {sections}."
        )
    elif diff is not None and diff.identical:
        summary = (
            f"{DRAFT_DISCLAIMER} No textual difference between "
            f"v{old_version.get('version_number')} and "
            f"v{new_version.get('version_number')}; metadata may have changed."
        )
        claims.append({
            "claim": "Extracted texts are identical across the two versions.",
            "claim_type": "textual_comparison",
            "citation_ids": [version_cid],
            "verification_status": "unverified",
        })
    else:
        summary = (
            f"{DRAFT_DISCLAIMER} Comparison withheld: extraction evidence "
            "is incomplete; flagged for human review."
        )
    report = {
        "document_title": document.get("title", ""),
        "issuing_authority": document.get("issuing_authority", ""),
        "jurisdiction": document.get("jurisdiction", "unknown"),
        "document_type": document.get("document_type", "unknown"),
        "official_source_url": url,        "published_date": document.get("published_at")
        if isinstance(document.get("published_at"), str) else None,
        "retrieved_at": new_version.get("retrieved_at", ""),
        "change_type": change_type,
        "summary": summary,
        "textual_changes": textual_changes,
        "affected_sections": (diff.affected_sections if diff is not None else []),
        "commencement": {
            "statement": "Not established from the extracted evidence",
            "date": None,
            "source_locator": None,
            "verification_status": "unverified",
        },
        "potentially_affected_groups": [],
        "related_documents": [],
        "claims": claims,
        "citations": citations,
        "warnings": warnings + json.loads(new_version.get("parser_warnings",
                                                          "[]")),
        "review_status": ("needs_changes"
                          if new_version.get("review_status") == "needs_review"
                          else "pending"),
    }
    validate_report(report)
    return report


def save_report(conn, document_id: int, old_version_id: int | None,
                new_version_id: int, report: dict) -> int:
    """Persist a validated report + citations. Returns the report id."""
    validate_report(report)
    old_row = (conn.execute("SELECT id FROM document_versions WHERE id=?",
                            (old_version_id,)).fetchone()
               if old_version_id else None)
    report_id = store.create_report(
        conn,
        document_id=document_id,
        old_version_id=old_row["id"] if old_row else None,
        new_version_id=new_version_id,
        change_type=report["change_type"],
        diff_text="\n".join(
            f"- {c['description']}" for c in report["textual_changes"]),
        summary=report["summary"],
        affected_sections=report["affected_sections"],
        claims=report["claims"],
        verification_status="unverified",
    )
    for citation in report["citations"]:
        store.add_citation(
            conn,
            change_report_id=report_id,
            document_version_id=new_version_id,
            locator_type=citation["locator_type"],
            locator_value=citation["locator_value"],
            quoted_text=citation["quoted_text"],
            source_url=citation["source_url"],
        )
    return report_id


def generate_for_document(conn, document_id: int) -> dict | None:
    """Generate + persist a report for the latest version pair.

    Returns ``{'report_id': ..., 'change_type': ...}`` or ``None`` when
    there is nothing new to report (single version already reported, or a
    report already exists for the latest pair).
    """
    versions = store.list_versions(conn, document_id)
    if not versions:
        return None
    new_row = _row_to_dict(versions[-1])
    old_row = _row_to_dict(versions[-2]) if len(versions) > 1 else None
    existing = store.find_report(
        conn, document_id,
        old_row.get("id") if old_row else None, new_row["id"])
    if existing is not None:
        return None
    document = _row_to_dict(store.get_document(conn, document_id))
    old_text = _read_version_text(old_row) if old_row else ""
    new_text = _read_version_text(new_row)
    report = build_report(document, old_row or None, new_row, old_text,
                          new_text)
    report_id = save_report(conn, document_id,
                            old_row.get("id") if old_row else None,
                            new_row["id"], report)
    conn.commit()
    return {"report_id": report_id, "change_type": report["change_type"],
            "document_id": document_id,
            "new_version_id": new_row["id"]}


def generate_pending(conn, limit: int = 100) -> list[dict]:
    """Backfill reports for documents missing one. Returns created summaries."""
    created: list[dict] = []
    for row in store.list_documents(conn, limit=limit * 5):
        if len(created) >= limit:
            break
        result = generate_for_document(conn, row["id"])
        if result is not None:
            created.append(result)
    return created


def utcnow() -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="milliseconds"))
