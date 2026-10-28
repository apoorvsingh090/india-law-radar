"""Apply a summariser to a stored report (Milestone 4).

Flow: load report + citations → rebuild the validated draft view →
run the summariser (heuristic default, external command only with
``--ai`` and configured ``ai.command``) → merge + re-validate the full
report → persist. Any failure is recorded in ``ai_attempts`` and leaves
the stored report untouched.
"""
from __future__ import annotations

import json

from lawradar.ai.base import AISummariserError
from lawradar.ai.external import CommandSummariser
from lawradar.ai.heuristic import HeuristicSummariser
from lawradar.db import store
from lawradar.reporting.schema import validate_report


def _utcnow() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def draft_view(conn, report_id: int) -> tuple[dict, dict]:
    """Rebuild the draft + evidence a summariser may use. Raises ValueError."""
    report = store.get_report(conn, report_id)
    if report is None:
        raise ValueError(f"unknown report id {report_id}")
    citations = store.list_citations(conn, report_id)
    by_number = []
    citation_ids = []
    for i, cite in enumerate(citations, start=1):
        cid = f"c{i}"
        citation_ids.append(cid)
        by_number.append({
            "citation_id": cid,
            "locator_type": cite["locator_type"],
            "locator_value": cite["locator_value"],
            "quoted_text": cite["quoted_text"],
            "source_url": cite["source_url"],
        })
    claims = json.loads(report["claims_json"])
    draft = {
        "summary": report["summary"],
        "claims": [dict(c) for c in claims],
        "warnings": [],
        "change_type": report["change_type"],
        "document_title": report["document_title"],
    }
    document = store.get_document(conn, report["document_id"])
    evidence = {
        "citation_ids": citation_ids,
        "citations": by_number,
        "official_source_url": (document["official_url"]
                                if document else ""),
        "change_type": report["change_type"],
    }
    return draft, evidence


def _remap_claims(result_claims: list[dict], count: int) -> list[dict]:
    """Keep c1..cN ids; reject anything outside the supplied evidence."""
    remapped = []
    for claim in result_claims:
        ids = []
        for cid in claim.get("citation_ids", []):
            if (isinstance(cid, str) and cid.startswith("c")
                    and cid[1:].isdigit() and 1 <= int(cid[1:]) <= count):
                ids.append(cid)
            else:
                raise AISummariserError(
                    f"claim references citation outside the evidence: {cid!r}")
        if not ids and not claim.get("unsupported", False):
            raise AISummariserError(
                "summariser claim has no evidence citations")
        remapped.append({
            "claim": claim["claim"],
            "claim_type": claim["claim_type"],
            "citation_ids": ids,
            "verification_status": "unverified",
            **({"unsupported": True} if claim.get("unsupported") else {}),
        })
    return remapped


def resummarise(conn, config, report_id: int,
                use_ai: bool = False) -> dict:
    """Run the summariser and persist the merged report. Never half-writes."""
    report = store.get_report(conn, report_id)
    if report is None:
        raise ValueError(f"unknown report id {report_id}")
    if report["published_at"]:
        raise ValueError(
            "refusing to re-summarise a published report; create a new "
            "draft/revision and approve it explicitly")
    attempts = json.loads(report["ai_attempts"] or "[]")
    draft, evidence = draft_view(conn, report_id)
    if use_ai:
        if not getattr(config, "ai_enabled", False):
            raise AISummariserError(
                "AI summarisation is disabled (ai.enabled=false); "
                "run without --ai or configure ai.command")
        summariser = CommandSummariser(getattr(config, "ai_command", ""))
    else:
        summariser = HeuristicSummariser()
    try:
        result = summariser.summarise(draft, evidence)
    except AISummariserError as exc:
        attempts.append({"at": _utcnow(), "summariser": summariser.name,
                         "status": "rejected", "error": str(exc)})
        store.set_ai_attempts(conn, report_id, attempts)
        conn.commit()
        raise
    # Merge: summary + warnings replaced, claims kept on evidence ids.
    citations = store.list_citations(conn, report_id)
    try:
        merged_claims = _remap_claims(result["claims"], len(citations))
    except AISummariserError as exc:
        attempts.append({"at": _utcnow(), "summariser": summariser.name,
                         "status": "rejected", "error": str(exc)})
        store.set_ai_attempts(conn, report_id, attempts)
        conn.commit()
        raise
    merged = {
        "document_title": report["document_title"],
        "issuing_authority": "",
        "jurisdiction": "unknown",
        "document_type": "unknown",
        "official_source_url": "",
        "change_type": report["change_type"],
        "summary": result["summary"],
        "textual_changes": [],
        "affected_sections": json.loads(report["affected_sections"] or "[]"),
        "commencement": {"statement": "Not established from the extracted "
                                      "evidence",
                         "date": None, "source_locator": None,
                         "verification_status": "unverified"},
        "potentially_affected_groups": [],
        "related_documents": [],
        "claims": merged_claims,
        "citations": [{"citation_id": f"c{i + 1}"} for i in range(len(citations))],
        "warnings": result.get("warnings", []),
        "review_status": "pending",
    }
    validate_report(merged)
    attempts.append({"at": _utcnow(), "summariser": summariser.name,
                     "status": "applied",
                     "warnings": result.get("warnings", [])})
    store.update_report_summary(
        conn, report_id, summary=result["summary"], claims=merged_claims,
        ai_attempts=attempts)
    conn.commit()
    return {"report_id": report_id, "summariser": summariser.name,
            "status": "applied"}
