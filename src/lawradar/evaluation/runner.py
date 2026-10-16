"""Pilot evaluation runner (Milestone 6).

Runs a curated, bounded fixture set through ingest → diff → report →
verify → review and measures the pilot acceptance targets. Results are
valid ONLY for this set (see SCOPE) — never a claim about Indian law
in general. Deterministic: same set, same numbers, every run.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from lawradar.db import store
from lawradar.ingestion.pipeline import ingest_bytes
from lawradar.reporting.verify import verify_report
from lawradar.sources.registry import SourceRecord

SCOPE = (
    "Bounded fixture set (7 cases, synthetic [FIXTURE] documents). "
    "Measures pipeline correctness on known inputs only. "
    "Does NOT generalise to official sources or real law."
)

DOC = {
    "source_id": "eval",
    "issuing_authority": "Fixture Authority",
    "jurisdiction": "central",
    "official_url": "https://example.invalid/eval",
}


def _html(title: str, *paras: str) -> bytes:
    body = "".join(f"<p>{p}</p>" for p in paras)
    return f"<html><body><h1>{title}</h1>{body}</body></html>".encode()


CASES = [
    {"name": "change_detected", "doc": "eval-change",
     "v1": _html("Eval Act", "Section 1 - Scope",
                 "File within thirty days of the quarter end date here."),
     "v2": _html("Eval Act", "Section 1 - Scope",
                 "File within forty-five days of the quarter end date here.",
                 "Section 2 - Late fee", "A late fee paragraph follows here."),
     "expect_change": "text_modified", "expect_sections": ["Section 1", "Section 2"]},
    {"name": "identical_no_dup", "doc": "eval-same",
     "v1": _html("Same Act", "Section 1 - Scope",
                 "A sufficiently long stable paragraph for dedup purposes."),
     "v2": None, "expect_change": None, "expect_sections": []},
    {"name": "metadata_only", "doc": "eval-meta", "title2": "Same Act (renamed)",
     "v1": _html("Same Act", "Section 1 - Scope",
                 "A sufficiently long stable paragraph for metadata checks."),
     "v2": "same-bytes", "expect_change": None, "expect_sections": []},
    {"name": "amendment_signal", "doc": "eval-amend",
     "v1": _html("Amend Act", "Section 1 - Scope",
                 "A sufficiently long base paragraph for amendment checks."),
     "v2": _html("Amend Act", "Section 1 - Scope",
                 "A sufficiently long base paragraph for amendment checks.",
                 "Amendment inserted by section nine of the amending text here."),
     "expect_change": "possible_amendment", "expect_sections": []},
    {"name": "corrigendum_signal", "doc": "eval-corr",
     "v1": _html("Corr Act", "Section 1 - Scope",
                 "A sufficiently long base paragraph for corrigendum checks."),
     "v2": _html("Corr Act", "Section 1 - Scope",
                 "A sufficiently long base paragraph for corrigendum checks.",
                 "Corrigendum: correction to the first schedule text here."),
     "expect_change": "corrigendum", "expect_sections": []},
    {"name": "unreadable_flagged", "doc": "eval-scan",
     "v1": b"<html><body><p>Hi</p></body></html>",
     "v2": b"<html><body><p>Yo</p></body></html>",
     "expect_change": "unknown", "expect_sections": []},
    {"name": "dates_unknown", "doc": "eval-dates",
     "v1": _html("Dates Act", "Section 1 - Scope",
                 "This Act comes into force on a date to be appointed later.",
                 "Different provisions commence on different appointed dates."),
     "v2": None, "expect_change": "new_document", "expect_sections": []},
]


@dataclass
class EvalResult:
    metrics: dict = field(default_factory=dict)
    cases: list[dict] = field(default_factory=list)


def run() -> EvalResult:
    """Execute the curated set in an isolated temp DB. Returns metrics."""
    tmp = Path(tempfile.mkdtemp(prefix="lawradar-eval-"))
    data_dir = tmp / "data"
    data_dir.mkdir()
    db_path = data_dir / "eval.db"
    store.init_db(db_path)
    conn = store.connect(db_path)
    try:
        store.upsert_source(conn, SourceRecord(
            id="eval", name="Eval", base_url="https://example.invalid/",
            access_method="manual_import", enabled=True))
        conn.commit()
        result = EvalResult()
        detected = 0
        expected_changes = 0
        material_claims = 0
        cited_claims = 0
        status_errors = 0
        for case in CASES:
            v1 = ingest_bytes(
                conn, source_document_id=case["doc"], title="Eval",
                raw_bytes=case["v1"], content_type="text/html",
                filename="c.html", data_dir=data_dir, **DOC)
            conn.commit()
            outcome: dict = {"case": case["name"], "v1": v1.status}
            if case["v2"] == "same-bytes":
                v2 = ingest_bytes(
                    conn, source_document_id=case["doc"],
                    title=case.get("title2", "Eval"), raw_bytes=case["v1"],
                    content_type="text/html", filename="c.html",
                    data_dir=data_dir, **DOC)
                conn.commit()
                outcome["v2"] = v2.status
                outcome["pass"] = v2.status == "duplicate"
            elif case["v2"] is not None:
                v2 = ingest_bytes(
                    conn, source_document_id=case["doc"], title="Eval",
                    raw_bytes=case["v2"], content_type="text/html",
                    filename="c.html", data_dir=data_dir, **DOC)
                conn.commit()
                report = store.list_reports(conn, document_id=v2.document_id)[0]
                claims = json.loads(report["claims_json"])
                material = [c for c in claims
                            if c["claim_type"] in ("source_fact",
                                                   "textual_comparison")]
                material_claims += len(material)
                cited_claims += sum(1 for c in material if c["citation_ids"])
                verify = verify_report(conn, report["id"])
                sections_ok = all(
                    any(s in a for a in json.loads(
                        report["affected_sections"]))
                    for s in case["expect_sections"])
                if case["expect_change"] == "unknown":
                    tasks = [t for t in store.list_review_tasks(conn)
                             if t["change_report_id"] == report["id"]]
                    outcome.update({
                        "v2": v2.status, "change_type": report["change_type"],
                        "verify": verify["status"],
                        "pass": (report["change_type"] == "unknown"
                                 and len(tasks) >= 1),
                    })
                else:
                    outcome.update({
                        "v2": v2.status, "change_type": report["change_type"],
                        "verify": verify["status"],
                        "pass": (report["change_type"] == case["expect_change"]
                                 and verify["status"] == "verified"
                                 and sections_ok),
                    })
                    expected_changes += 1
                    detected += outcome["pass"]
            else:
                if case["expect_change"] == "unknown":
                    report = store.list_reports(conn,
                                                document_id=v1.document_id)[0]
                    tasks = [t for t in store.list_review_tasks(conn)
                             if t["change_report_id"] == report["id"]]
                    outcome["pass"] = (
                        report["change_type"] == "unknown"
                        and report["verification_status"] == "unverified"
                        and len(tasks) >= 1)
                elif case["expect_change"] == "new_document":
                    report = store.list_reports(conn,
                                                document_id=v1.document_id)[0]
                    # Commencement honesty is schema-enforced (build_report
                    # always emits unverified/None); here we check the type.
                    outcome["pass"] = report["change_type"] == "new_document"
                else:  # identical_no_dup: single version, single report
                    outcome["pass"] = (
                        store.count_versions(conn, v1.document_id) == 1)
            result.cases.append(outcome)
        # Commencement/published honesty across all reports.
        for row in conn.execute("SELECT * FROM change_reports").fetchall():
            if row["verification_status"] not in (
                    "unverified", "citation_checked", "approved",
                    "rejected", "needs_changes"):
                status_errors += 1
            if row["published_at"] is not None:
                status_errors += 1  # nothing may self-publish in eval
        failed_runs = [r for r in store.latest_runs(conn, 1000)
                       if r["status"] in ("failed", "partial")]
        result.metrics = {
            "scope": SCOPE,
            "cases": len(CASES),
            "cases_passed": sum(1 for c in result.cases if c["pass"]),
            "change_recall": (detected / expected_changes
                              if expected_changes else 1.0),
            "citation_correctness": (cited_claims / material_claims
                                     if material_claims else 1.0),
            "status_errors": status_errors,
            "failed_runs_visible": len(failed_runs),
        }
        return result
    finally:
        conn.close()
