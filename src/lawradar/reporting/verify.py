"""Deterministic citation verification (Milestone 4).

A machine check, not a human review: every citation attached to a report
is tested against the stored evidence. Per-citation results are persisted;
the report itself is only relabelled, never published, by this step.
Publication remains an explicit human ``review --approve``.
"""
from __future__ import annotations

from pathlib import Path

from lawradar.db import store
from lawradar.ingestion.hashing import normalize_text


def _version_text(conn, version_id: int) -> str:
    row = conn.execute(
        "SELECT extracted_text_path FROM document_versions WHERE id=?",
        (version_id,)).fetchone()
    if not row or not row["extracted_text_path"]:
        return ""
    try:
        return Path(row["extracted_text_path"]).read_text(encoding="utf-8")
    except OSError:
        return ""


def verify_citation(citation: dict, *, official_url: str,
                    version_text: str) -> dict:
    """Check one citation. Returns ``{'ok': bool, 'reasons': [...]}``."""
    reasons: list[str] = []
    locator = (citation.get("locator_value") or "").strip()
    if not locator:
        reasons.append("empty locator")
    if not (citation.get("locator_type") or "").strip():
        reasons.append("empty locator type")
    quoted = (citation.get("quoted_text") or "").strip()
    if quoted and version_text:
        # Quotes are whitespace-collapsed (and possibly truncated) at
        # creation; compare on the same normalised basis.
        marker = " …[truncated]"
        candidate = quoted[:-len(marker)] if quoted.endswith(marker) else quoted
        if (citation.get("locator_type") == "text span"
                and len(candidate) > 20
                and normalize_text(candidate) not in normalize_text(version_text)):
            reasons.append("quoted text not found in extracted version text")
    url = (citation.get("source_url") or "").strip()
    if url and official_url and url != official_url:
        reasons.append(f"source URL differs from official URL {official_url!r}")
    return {"ok": not reasons, "reasons": reasons}


def verify_report(conn, report_id: int) -> dict:
    """Verify all citations of a report and persist per-citation results."""
    report = store.get_report(conn, report_id)
    if report is None:
        raise ValueError(f"unknown report id {report_id}")
    document = store.get_document(conn, report["document_id"])
    official_url = (document["official_url"] if document else "") or ""
    version_text = _version_text(conn, report["new_version_id"])
    citations = store.list_citations(conn, report_id)
    results: list[dict] = []
    failures = 0
    for citation in citations:
        outcome = verify_citation(
            dict(citation), official_url=official_url,
            version_text=version_text)
        status = "verified" if outcome["ok"] else "failed"
        if not outcome["ok"]:
            failures += 1
        store.set_citation_verification(conn, citation["id"], status)
        results.append({"citation_db_id": citation["id"],
                        "locator_type": citation["locator_type"],
                        "locator_value": citation["locator_value"],
                        "status": status,
                        "reasons": outcome["reasons"]})
    if not citations:
        summary_status = "failed"
    elif failures:
        summary_status = "failed"
    else:
        summary_status = "verified"
    if summary_status == "verified" and report["verification_status"] == "unverified":
        store.set_report_verification(conn, report_id, "citation_checked")
    conn.commit()
    return {"report_id": report_id, "status": summary_status,
            "checked": len(citations), "failed": failures,
            "results": results}
