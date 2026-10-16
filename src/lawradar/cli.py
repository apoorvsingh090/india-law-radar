"""Command-line interface for India Law Radar (Milestone 4).

Implemented commands (all functional, no placeholders):
  lawradar init              — create data dir, local settings.yaml, migrate db
  lawradar health            — verify config loads, data dir writable, sqlite works
  lawradar sources list      — show registry (DB-synced) with check timestamps
  lawradar ingest <id>       — ingest one source (fixture / manual --file / http probe)
  lawradar ingest --all      — ingest all enabled sources
  lawradar documents list    — list stored documents + version counts
  lawradar documents show    — show a document with its versions
  lawradar documents search  — keyword search over title/authority/ids
  lawradar reports list      — change reports with type + verification status
  lawradar reports show <id> — report detail with claims + citations
  lawradar reports generate  — backfill reports missed by auto-generation
  lawradar reports verify <id> — deterministic citation check
  lawradar reports summarise <id> [--ai] — reword summary (validated)
  lawradar review --list     — pending human-review queue
  lawradar review <id> --approve|--reject|--changes --notes "..."
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from lawradar import __version__
from lawradar.config import ensure_data_dir, find_config_file, load_settings
from lawradar.logging_config import get_logger, setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lawradar",
        description="India Law Radar — source-verifiable Indian legal change monitoring",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default=None, help="Path to settings YAML file")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override log level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialise local data dir and config")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing files")

    p_health = sub.add_parser("health", help="Check local setup health")
    p_health.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit non-zero if any check reports a warning",
    )

    p_sources = sub.add_parser("sources", help="Inspect the source registry")
    sources_sub = p_sources.add_subparsers(dest="sources_command", required=True)
    sources_sub.add_parser("list", help="List sources with check status")
    p_check = sources_sub.add_parser(
        "check", help="Record a connectivity probe (no fetch in M2)")
    p_check.add_argument("source_id", help="Source id to probe")

    p_ingest = sub.add_parser("ingest", help="Ingest documents from a source")
    p_ingest.add_argument("source_id", nargs="?",
                          help="Source id (or omit with --all)")
    p_ingest.add_argument("--all", action="store_true",
                          help="Ingest all enabled sources")
    p_ingest.add_argument("--limit", type=int, default=100,
                          help="Max documents per source")
    p_ingest.add_argument("--file", default=None,
                          help="Local file (manual_import sources)")
    p_ingest.add_argument("--title", default="",
                          help="Title for a manual import")
    p_ingest.add_argument("--doc-id", default="",
                          help="Source document id for a manual import")
    p_ingest.add_argument("--sources-file", default=None,
                          help="Alternate sources YAML")

    p_docs = sub.add_parser("documents", help="Inspect stored documents")
    docs_sub = p_docs.add_subparsers(dest="documents_command", required=True)
    p_list = docs_sub.add_parser("list", help="List stored documents")
    p_list.add_argument("--limit", type=int, default=50)
    p_show = docs_sub.add_parser("show", help="Show a document + versions")
    p_show.add_argument("document_id", type=int)
    p_search = docs_sub.add_parser("search", help="Keyword search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=20)

    p_reports = sub.add_parser("reports", help="Inspect change reports")
    reports_sub = p_reports.add_subparsers(dest="reports_command", required=True)
    p_rlist = reports_sub.add_parser("list", help="List change reports")
    p_rlist.add_argument("--document", type=int, default=None,
                         help="Only reports for this document id")
    p_rlist.add_argument("--limit", type=int, default=50)
    p_rshow = reports_sub.add_parser("show", help="Show a report + citations")
    p_rshow.add_argument("report_id", type=int)
    p_rgen = reports_sub.add_parser(
        "generate", help="Backfill missing reports (ingest already auto-generates)")
    p_rgen.add_argument("--document", type=int, default=None)
    p_rgen.add_argument("--limit", type=int, default=100)
    p_rverify = reports_sub.add_parser(
        "verify", help="Deterministic citation check (not a human review)")
    p_rverify.add_argument("report_id", type=int)
    p_rsum = reports_sub.add_parser(
        "summarise", help="Reword a report summary (heuristic; --ai if configured)")
    p_rsum.add_argument("report_id", type=int)
    p_rsum.add_argument("--ai", action="store_true",
                        help="Use the configured external AI command")

    p_review = sub.add_parser("review", help="Human review queue + decisions")
    p_review.add_argument("report_id", nargs="?", type=int, default=None,
                          help="Report id to decide (omit with --list)")
    p_review.add_argument("--list", action="store_true",
                          help="Show the review queue")
    p_review.add_argument("--status", default="pending",
                          help="Queue filter for --list")
    p_review.add_argument("--approve", action="store_true")
    p_review.add_argument("--reject", action="store_true")
    p_review.add_argument("--changes", action="store_true",
                          help="Request changes (same as needs_changes)")
    p_review.add_argument("--reviewer", default="",
                          help="Reviewer name (default: local)")
    p_review.add_argument("--notes", default="",
                          help="Review notes (required to reject/request changes)")
    p_review.add_argument("--limit", type=int, default=50)
    return parser


def _effective_config(args: argparse.Namespace):
    import os

    if args.data_dir:
        os.environ["LAWRADAR_DATA_DIR"] = args.data_dir
    if args.log_level:
        os.environ["LAWRADAR_LOG_LEVEL"] = args.log_level
    config = load_settings(args.config)
    # CLI flags win over file/env for these two fields.
    if args.data_dir:
        config.data_dir = args.data_dir
    if args.log_level:
        config.log_level = args.log_level.upper()
    return config


def cmd_init(args: argparse.Namespace) -> int:
    config = _effective_config(args)
    logger = setup_logging(config.log_level, config.log_file)
    data_dir = ensure_data_dir(config)
    logger.info("data dir ready: %s", data_dir)

    # Copy example settings to config/settings.yaml when missing.
    dest = Path("config/settings.yaml")
    example = Path("config/settings.example.yaml")
    copied = False
    if dest.exists() and not args.force:
        logger.info("config already exists: %s (use --force to overwrite)", dest)
    elif example.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and args.force:
            dest.unlink()
        shutil.copyfile(example, dest)
        copied = True
        logger.info("created %s from example", dest)
    else:
        logger.warning("example config not found at %s; skipping copy", example)

    # Migrate the sqlite db so later milestones have a stable schema.
    db_path = _sqlite_path(config.db_url, data_dir)
    if db_path is not None:
        from lawradar.db import store as _store

        applied = _store.init_db(db_path)
        logger.info("sqlite ready: %s (migrations applied: %s)",
                    db_path, applied or "none pending")

    payload = {
        "status": "ok",
        "data_dir": str(data_dir),
        "config_copied": copied,
        "config_path": str(find_config_file(args.config) or dest),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Initialised {APP_LABEL}: data_dir={data_dir}")
        if copied:
            print(f"Created {dest} — edit it to suit your machine.")
        print("Next: run `lawradar health` to verify the setup.")
    return 0


APP_LABEL = "India Law Radar v0.4.0 (Milestone 4)"


def _sqlite_path(db_url: str, data_dir: Path) -> Path | None:
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return None
    raw = db_url[len(prefix):]
    path = Path(raw)
    if not path.is_absolute():
        # Resolve relative sqlite paths against the repo root when the
        # configured data dir is the default ./data, else against data_dir.
        if str(data_dir) in ("./data", "data", ".\\data"):
            return Path(raw)
        return data_dir / path.name
    return path


def run_health_checks(config) -> dict:
    """Run deterministic local checks. Never touches the network."""
    checks: dict = {}
    # 1. Config loads (we already have it — record source).
    checks["config_loads"] = {
        "ok": True,
        "detail": f"config_path={config.config_path or '(defaults)'}",
    }
    # 2. Data dir exists and is writable.
    try:
        data_dir = ensure_data_dir(config)
        probe = data_dir / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks["data_dir_writable"] = {"ok": True, "detail": str(data_dir)}
    except Exception as exc:  # noqa: BLE001
        checks["data_dir_writable"] = {"ok": False, "detail": str(exc)}
    # 3. SQLite round-trip.
    try:
        db_path = _sqlite_path(config.db_url, Path(config.data_dir))
        if db_path is None:
            checks["sqlite"] = {
                "ok": True,
                "warning": True,
                "detail": f"non-sqlite db_url configured ({config.db_url}); skipped",
            }
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS _meta (k TEXT PRIMARY KEY, v TEXT)")
                conn.execute(
                    "INSERT OR IGNORE INTO _meta (k, v) VALUES ('schema_version', 'm1')"
                )
                conn.commit()
                try:
                    applied = conn.execute(
                        "SELECT COUNT(*) FROM _migrations").fetchone()[0]
                    mig_detail = f", migrations={applied}"
                except sqlite3.OperationalError:
                    mig_detail = ", migrations=none"
                checks["sqlite"] = {
                    "ok": True,
                    "detail": f"{db_path}{mig_detail}",
                }
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        checks["sqlite"] = {"ok": False, "detail": str(exc)}
    return checks


def cmd_health(args: argparse.Namespace) -> int:
    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    logger = get_logger("lawradar")
    checks = run_health_checks(config)
    all_ok = all(check.get("ok") for check in checks.values())
    has_warning = any(check.get("warning") for check in checks.values())
    status = "ok" if all_ok else "fail"
    if args.json:
        print(json.dumps({"status": status, "checks": checks}, indent=2))
    else:
        print(f"{APP_LABEL} — health: {status.upper()}")
        for name, check in checks.items():
            mark = "PASS" if check.get("ok") else "FAIL"
            extra = " (warning)" if check.get("warning") else ""
            print(f"  [{mark}{extra}] {name}: {check.get('detail')}")
        if not all_ok:
            print("Some checks failed. See details above; run `lawradar init` first.", file=sys.stderr)
    logger.info("health check finished: %s", status)
    if not all_ok:
        return 1
    if has_warning and args.fail_on_warning:
        return 2
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.ingestion.pipeline import _db_path, sync_registry
    from lawradar.sources.registry import load_sources

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    store.init_db(_db_path(config))
    conn = store.connect(_db_path(config))
    try:
        sources = load_sources(getattr(args, "sources_file", None) or None)
        sync_registry(conn, sources)
        rows = store.list_sources(conn)
    finally:
        conn.close()
    if args.sources_command == "check":
        wanted = args.source_id
        match = next((r for r in rows if r["id"] == wanted), None)
        if match is None:
            print(f"unknown source {wanted!r}", file=sys.stderr)
            return 2
        print(f"{match['id']}: access_method={match['access_method']} "
              f"enabled={bool(match['enabled'])} terms={match['terms_review_status']}")
        print("M2 probe: registry entry present; real fetching is per-adapter "
              "(use `lawradar ingest` for fixture/manual sources).")
        return 0
    # list
    if args.json:
        print(json.dumps([dict(r) for r in rows], indent=2))
    else:
        if not rows:
            print("No sources configured. See config/sources.example.yaml.")
        for r in rows:
            state = "enabled" if r["enabled"] else "disabled"
            print(f"- {r['id']} [{state}] {r['name']}")
            print(f"  {r['base_url']} | {r['access_method']} | {r['jurisdiction']} "
                  f"| terms={r['terms_review_status']}")
            print(f"  last_check={r['last_checked_at'] or '-'} "
                  f"last_success={r['last_success_at'] or '-'} "
                  f"error={r['last_error'] or '-'}")
            if r["coverage_notes"]:
                print(f"  coverage: {r['coverage_notes']}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from lawradar.ingestion.pipeline import run_ingestion

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    if not args.all and not args.source_id:
        print("specify a source id or --all", file=sys.stderr)
        return 2
    try:
        summary = run_ingestion(
            config,
            getattr(args, "sources_file", None) or None,
            source_id=args.source_id,
            ingest_all=args.all,
            limit=args.limit,
            manual_file=args.file,
            manual_title=args.title,
            manual_doc_id=args.doc_id,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for run in summary["runs"]:
            print(f"source run {run['run_id']}: {run['status']} "
                  f"(discovered={run.get('discovered', 0)} "
                  f"downloaded={run.get('downloaded', 0)} "
                  f"changed={run.get('changed', 0)} "
                  f"failed={run.get('failed', 0)})")
            for err in run.get("errors", []):
                print(f"  error: {err}")
    failed = sum(1 for r in summary["runs"] if r["status"] in ("failed", "partial"))
    return 1 if failed else 0


def cmd_documents(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.ingestion.pipeline import _db_path

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    store.init_db(_db_path(config))
    conn = store.connect(_db_path(config))
    try:
        if args.documents_command == "list":
            rows = store.list_documents(conn, args.limit)
            if args.json:
                print(json.dumps([dict(r) for r in rows], indent=2))
            else:
                for r in rows:
                    print(f"[{r['id']}] {r['title']} "
                          f"({r['document_type']}, {r['jurisdiction']}) "
                          f"versions={r['versions']}")
                if not rows:
                    print("No documents stored yet. Run `lawradar ingest <source-id>`.")
        elif args.documents_command == "show":
            doc = store.get_document(conn, args.document_id)
            if doc is None:
                print(f"unknown document id {args.document_id}", file=sys.stderr)
                return 2
            versions = store.list_versions(conn, doc["id"])
            payload = {"document": dict(doc),
                       "versions": [dict(v) for v in versions]}
            if args.json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(f"[{doc['id']}] {doc['title']}")
                print(f"  source={doc['source_id']} ref={doc['source_document_id']} "
                      f"type={doc['document_type']} authority={doc['issuing_authority']}")
                print(f"  official_url={doc['official_url']}")
                for v in versions:
                    print(f"  v{v['version_number']} sha={v['content_sha256'][:12]}… "
                          f"extraction={v['extraction_status']} "
                          f"review={v['review_status']} retrieved={v['retrieved_at']}")
        elif args.documents_command == "search":
            rows = store.search_documents(conn, args.query, args.limit)
            if args.json:
                print(json.dumps([dict(r) for r in rows], indent=2))
            else:
                for r in rows:
                    print(f"[{r['id']}] {r['title']} "
                          f"({r['source_id']}/{r['source_document_id']})")
                if not rows:
                    print(f"No matches for {args.query!r}.")
    finally:
        conn.close()
    return 0


def cmd_reports(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.ingestion.pipeline import _db_path
    from lawradar.reporting.generate import generate_for_document, generate_pending

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    store.init_db(_db_path(config))
    conn = store.connect(_db_path(config))
    try:
        if args.reports_command == "list":
            rows = store.list_reports(conn, args.limit, args.document)
            if args.json:
                print(json.dumps([dict(r) for r in rows], indent=2,
                                 default=str))
            else:
                for r in rows:
                    old = r["old_version_id"]
                    pair = (f"v{old}->v{r['new_version_id']}"
                            if old is not None
                            else f"v{r['new_version_id']} (first)")
                    pub = "published" if r["published_at"] else "unpublished"
                    print(f"[{r['id']}] {r['document_title']} "
                          f"(doc={r['document_id']} {pair}) "
                          f"type={r['change_type']} status={r['verification_status']} "
                          f"{pub}")
                if not rows:
                    print("No reports yet. Ingest a source first.")
        elif args.reports_command == "show":
            report = store.get_report(conn, args.report_id)
            if report is None:
                print(f"unknown report id {args.report_id}", file=sys.stderr)
                return 2
            citations = store.list_citations(conn, report["id"])
            import json as _json

            claims = _json.loads(report["claims_json"])
            affected = _json.loads(report["affected_sections"])
            if args.json:
                payload = dict(report)
                payload["claims"] = claims
                payload["affected_sections"] = affected
                payload["citations"] = [dict(c) for c in citations]
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(f"[{report['id']}] {report['document_title']}")
                print(f"  change_type={report['change_type']} "
                      f"verification={report['verification_status']} "
                      f"published={report['published_at'] or 'no'}")
                print(f"  summary: {report['summary']}")
                if affected:
                    print(f"  affected: {', '.join(affected)}")
                print("  claims:")
                for claim in claims:
                    print(f"    - [{claim['claim_type']}] {claim['claim']}")
                    print(f"      citations: {', '.join(claim['citation_ids'])}")
                print("  citations:")
                for cite in citations:
                    print(f"    - {cite['locator_type']}: {cite['locator_value']}")
        elif args.reports_command == "generate":
            if args.document is not None:
                result = generate_for_document(conn, args.document)
                created = [result] if result else []
            else:
                created = generate_pending(conn, args.limit)
            if args.json:
                print(json.dumps(created, indent=2, default=str))
            else:
                for item in created:
                    print(f"report {item['report_id']}: doc={item['document_id']} "
                          f"type={item['change_type']}")
                if not created:
                    print("Nothing to generate — all versions already reported.")
        elif args.reports_command == "verify":
            from lawradar.reporting.verify import verify_report

            try:
                outcome = verify_report(conn, args.report_id)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            if args.json:
                print(json.dumps(outcome, indent=2))
            else:
                print(f"report {outcome['report_id']}: {outcome['status']} "
                      f"(checked={outcome['checked']} failed={outcome['failed']})")
                for item in outcome["results"]:
                    mark = "ok" if item["status"] == "verified" else "FAIL"
                    print(f"  [{mark}] {item['locator_type']}: "
                          f"{item['locator_value']}")
                    for reason in item["reasons"]:
                        print(f"    - {reason}")
            return 0 if outcome["status"] == "verified" else 1
        elif args.reports_command == "summarise":
            from lawradar.ai.base import AISummariserError
            from lawradar.reporting.summarise import resummarise

            try:
                outcome = resummarise(conn, config, args.report_id,
                                      use_ai=args.ai)
            except (ValueError, AISummariserError) as exc:
                print(f"summarise rejected: {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(outcome, indent=2))
            else:
                print(f"report {outcome['report_id']}: summary "
                      f"{outcome['status']} via {outcome['summariser']}")
    finally:
        conn.close()
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.ingestion.pipeline import _db_path
    from lawradar.review.queue import audit_trail, queue_summary, resolve

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    store.init_db(_db_path(config))
    conn = store.connect(_db_path(config))
    try:
        if args.list or args.report_id is None:
            tasks = store.list_review_tasks(conn, args.status, args.limit)
            summary = queue_summary(conn)
            if args.json:
                print(json.dumps({"summary": summary,
                                  "tasks": [dict(t) for t in tasks]},
                                 indent=2, default=str))
            else:
                print(f"review queue: {summary['pending']} pending / "
                      f"{summary['total']} total "
                      f"(approved={summary['approved']} "
                      f"rejected={summary['rejected']} "
                      f"needs_changes={summary['needs_changes']})")
                for task in tasks:
                    print(f"  [task {task['id']}] report={task['change_report_id']} "
                          f"status={task['status']} severity={task['severity']}")
                    print(f"    reason: {task['reason']}")
            return 0
        decisions = [name for name, wanted in
                     (("approved", args.approve), ("rejected", args.reject),
                      ("needs_changes", args.changes)) if wanted]
        if len(decisions) != 1:
            print("choose exactly one of --approve, --reject, --changes",
                  file=sys.stderr)
            return 2
        try:
            outcome = resolve(conn, report_id=args.report_id,
                              decision=decisions[0], reviewer=args.reviewer,
                              notes=args.notes)
        except Exception as exc:  # noqa: BLE001 — ReviewError/ValueError
            print(f"review rejected: {exc}", file=sys.stderr)
            return 1
        trail = audit_trail(conn, args.report_id)
        if args.json:
            print(json.dumps({**outcome, "audit_trail": trail}, indent=2,
                             default=str))
        else:
            print(f"report {outcome['report_id']}: {outcome['decision']} "
                  f"by {outcome['reviewer']} "
                  f"(tasks resolved: {outcome['tasks_resolved']})")
            print(f"  audit trail entries: {len(trail)}")
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "health":
        return cmd_health(args)
    if args.command == "sources":
        return cmd_sources(args)
    if args.command == "ingest":
        return cmd_ingest(args)
    if args.command == "documents":
        return cmd_documents(args)
    if args.command == "reports":
        return cmd_reports(args)
    if args.command == "review":
        return cmd_review(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
