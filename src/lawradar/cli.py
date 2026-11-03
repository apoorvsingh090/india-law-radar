"""Command-line interface for India Law Radar (Milestone 21).

Implemented commands (all functional, no placeholders):
  lawradar init              — create data dir, local settings.yaml, migrate db
  lawradar health            — verify config loads, data dir writable, sqlite works
  lawradar status            — operator snapshot (sources, queue, exports, backups)
  lawradar sources list      — show registry (DB-synced) with check timestamps
  lawradar ingest <id>       — ingest one source (fixture / manual --file / http probe)
  lawradar ingest --all      — ingest all enabled sources
  lawradar watch [--once]    — sweep due sources on schedule (the radar loop)
  lawradar documents list    — list stored documents + version counts
  lawradar documents show    — show a document with its versions
  lawradar documents search  — keyword search over title/authority/ids
  lawradar reports list      — change reports with type + verification status
  lawradar reports show <id> — report detail with claims + citations
  lawradar reports generate  — backfill reports missed by auto-generation
  lawradar reports verify <id> — deterministic citation check
  lawradar reports summarise <id> [--ai] — reword summary (validated)
  lawradar reports brief <id> [--out PATH] — approved report as Markdown
  lawradar review --list     — pending human-review queue
  lawradar review <id> --approve|--reject|--changes --notes "..."
  lawradar notify list       — webhook delivery attempts (audit/triage)
  lawradar notify send       — deliver published reports to pending targets
  lawradar bundles create <id> — export an approved report as evidence zip
  lawradar bundles verify PATH — fail-closed offline verification of a bundle
  lawradar bundles list      — export audit trail (all or per report)
  lawradar serve [--host 127.0.0.1] [--port 8080] [--token ...]
  lawradar eval                run the curated pilot evaluation set
  lawradar feedback list       triage user error reports
  lawradar backup create       verified SQLite snapshot + checksum + manifest
  lawradar backup verify PATH  fail closed unless integrity/checksum agree
  lawradar backup restore PATH --force  safety-snapshot, then restore
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

    sub.add_parser(
        "status", help="Operator snapshot (sources, queue, exports, backups)")

    p_sources = sub.add_parser("sources", help="Inspect the source registry")
    sources_sub = p_sources.add_subparsers(dest="sources_command", required=True)
    sources_sub.add_parser("list", help="List sources with check status")
    p_sources_health = sources_sub.add_parser(
        "health", help="Per-source health/staleness (exit 1 if unhealthy)")
    p_sources_health.add_argument(
        "--sources-file", default=None, help="Alternate sources YAML")
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
    p_ingest.add_argument("--url", default="",
                          help="Official URL you downloaded --file from "
                               "(recorded as provenance)")
    p_ingest.add_argument("--sources-file", default=None,
                          help="Alternate sources YAML")

    p_watch = sub.add_parser(
        "watch", help="Sweep due enabled sources on their poll schedule")
    p_watch.add_argument("--once", action="store_true",
                         help="Run a single sweep and exit (cron/"
                              "scheduled-task friendly)")
    p_watch.add_argument("--poll-seconds", type=float, default=300.0,
                         help="Sleep between sweeps when looping "
                              "(default 300)")
    p_watch.add_argument("--max-sweeps", type=int, default=None,
                         help="Stop after N sweeps (default: until Ctrl-C)")
    p_watch.add_argument("--limit", type=int, default=100,
                         help="Max documents per source per sweep")
    p_watch.add_argument("--sources-file", default=None,
                         help="Alternate sources YAML")

    p_docs = sub.add_parser("documents", help="Inspect stored documents")
    docs_sub = p_docs.add_subparsers(dest="documents_command", required=True)
    p_list = docs_sub.add_parser("list", help="List stored documents")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--source", default=None,
                        help="Only documents from this source id")
    p_list.add_argument("--type", default=None,
                        help="Only this document_type")
    p_list.add_argument("--jurisdiction", default=None,
                        help="Only this jurisdiction")
    p_show = docs_sub.add_parser("show", help="Show a document + versions")
    p_show.add_argument("document_id", type=int)
    p_search = docs_sub.add_parser("search", help="Keyword search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=20)
    p_search.add_argument("--source", default=None,
                          help="Only documents from this source id")
    p_search.add_argument("--type", default=None,
                          help="Only this document_type")
    p_search.add_argument("--jurisdiction", default=None,
                          help="Only this jurisdiction")

    p_reports = sub.add_parser("reports", help="Inspect change reports")
    reports_sub = p_reports.add_subparsers(dest="reports_command", required=True)
    p_rlist = reports_sub.add_parser("list", help="List change reports")
    p_rlist.add_argument("--document", type=int, default=None,
                         help="Only reports for this document id")
    p_rlist.add_argument("--limit", type=int, default=50)
    p_rlist.add_argument("--type", dest="change_type", default=None,
                         help="Only this change_type (e.g. text_modified)")
    p_rlist.add_argument("--status", dest="verification", default=None,
                         help="Only this verification_status (e.g. approved)")
    p_rlist.add_argument("--since", default=None,
                         help="Only reports created on/after YYYY-MM-DD (UTC)")
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
    p_rbrief = reports_sub.add_parser(
        "brief", help="Render an approved report as shareable Markdown")
    p_rbrief.add_argument("report_id", type=int)
    p_rbrief.add_argument("--out", default=None,
                          help="Write to PATH instead of stdout")

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

    p_notify = sub.add_parser(
        "notify", help="Outbound webhook deliveries (approved reports)")
    notify_sub = p_notify.add_subparsers(dest="notify_command", required=True)
    p_nlist = notify_sub.add_parser(
        "list", help="Recent delivery attempts (audit + triage)")
    p_nlist.add_argument("--report", type=int, default=None,
                         help="Only attempts for this report id")
    p_nlist.add_argument("--status", default=None,
                         help="Filter by delivered/failed")
    p_nlist.add_argument("--limit", type=int, default=50)
    p_nsend = notify_sub.add_parser(
        "send", help="Deliver published reports to pending webhook targets")
    p_nsend.add_argument("--report", type=int, default=None,
                         help="Deliver only this report id")
    p_nsend.add_argument("--limit", type=int, default=50)

    p_serve = sub.add_parser("serve", help="Run the local web interface")
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="Bind address (keep 127.0.0.1 unless proxied)")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--token", default="",
                         help="Shared secret gating review POSTs (else open "
                              "on loopback)")

    sub.add_parser("eval", help="Run the curated pilot evaluation set")

    p_feedback = sub.add_parser("feedback", help="Triage user error reports")
    feedback_sub = p_feedback.add_subparsers(dest="feedback_command",
                                             required=True)
    p_flist = feedback_sub.add_parser("list", help="List feedback")
    p_flist.add_argument("--status", default=None)
    p_flist.add_argument("--limit", type=int, default=50)
    p_fresolve = feedback_sub.add_parser("resolve", help="Mark resolved")
    p_fresolve.add_argument("feedback_id", type=int)

    p_backup = sub.add_parser(
        "backup", help="Create/verify/restore verified SQLite backups")
    backup_sub = p_backup.add_subparsers(
        dest="backup_command", required=True)
    p_bcreate = backup_sub.add_parser(
        "create", help="Snapshot the database + checksum + manifest")
    p_bcreate.add_argument(
        "--out", default=None, help="Directory (default: <db dir>/backups)")
    p_bcreate.add_argument(
        "--keep", type=int, default=0,
        help="Keep only N recent lawradar backups in --out (0 = keep all)")
    p_bverify = backup_sub.add_parser(
        "verify", help="Read-only checksum/integrity/manifest check")
    p_bverify.add_argument("backup_path", help="Path to the .db backup")
    p_brestore = backup_sub.add_parser(
        "restore", help="Verify, safety-snapshot, then atomically replace")
    p_brestore.add_argument("backup_path", help="Path to the .db backup")
    p_brestore.add_argument(
        "--force", action="store_true",
        help="Required when the target database already exists")

    p_bundles = sub.add_parser(
        "bundles", help="Offline-verifiable evidence exports (approved reports)")
    bundles_sub = p_bundles.add_subparsers(
        dest="bundles_command", required=True)
    p_xcreate = bundles_sub.add_parser(
        "create", help="Export one approved report as a verifiable bundle")
    p_xcreate.add_argument("report_id", type=int)
    p_xcreate.add_argument(
        "--out", default=None,
        help="Output directory (default: <data-dir>/bundles)")
    p_xverify = bundles_sub.add_parser(
        "verify", help="Read-only fail-closed verification of a bundle")
    p_xverify.add_argument("bundle_path", help="Path to evidence bundle .zip")
    p_xlist = bundles_sub.add_parser(
        "list", help="Export history recorded in the audit table")
    p_xlist.add_argument(
        "--report", type=int, default=None,
        help="Only bundles for this report id")
    p_xlist.add_argument("--limit", type=int, default=50)
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


APP_LABEL = f"India Law Radar v{__version__} (Milestone 21)"


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
                journal = conn.execute(
                    "PRAGMA journal_mode").fetchone()[0]
                checks["sqlite"] = {
                    "ok": True,
                    "detail": f"{db_path}{mig_detail}, journal={journal}",
                }
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        checks["sqlite"] = {"ok": False, "detail": str(exc)}
    # 4. Notification target config (local-only, never networked).
    try:
        from lawradar.notify.dispatch import targets_from_config

        targets = targets_from_config(config)
        enabled = [t for t in targets if t.enabled]
        if not getattr(config, "notify_enabled", False):
            checks["notify_config"] = {
                "ok": True,
                "detail": "webhook notifications disabled",
            }
        elif not enabled:
            checks["notify_config"] = {
                "ok": True,
                "warning": True,
                "detail": "notifications enabled but no webhook targets "
                          "configured",
            }
        else:
            names = ", ".join(t.name for t in enabled)
            checks["notify_config"] = {
                "ok": True,
                "detail": f"webhook targets: {names}",
            }
    except Exception as exc:  # noqa: BLE001
        checks["notify_config"] = {"ok": False, "detail": str(exc)}
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


def cmd_status(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.ingestion.pipeline import _db_path
    from lawradar.status import collect_status, format_status

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    db_path = _db_path(config)
    if not db_path.exists():
        print("no database yet - run `lawradar init` first", file=sys.stderr)
        return 1
    conn = store.connect(db_path)
    try:
        snapshot = collect_status(conn, config)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(snapshot, indent=2, default=str))
    else:
        print(format_status(snapshot))
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
    if args.sources_command == "health":
        from lawradar.ingestion.health import evaluate_sources, summarize

        summary = summarize(evaluate_sources([dict(r) for r in rows]))
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            if not summary["sources"]:
                print("No sources configured. See config/sources.example.yaml.")
            for item in summary["sources"]:
                due = (f" next_due={item['next_due_at']}"
                       if item["next_due_at"] else "")
                print(f"- {item['source_id']}: {item['status']} - "
                      f"{item['detail']}{due}")
            print(f"health: {'OK' if summary['healthy'] else 'FAILED'} "
                  f"({summary['monitored']} monitored, "
                  f"{summary['stale']} stale, {summary['failing']} failing)")
        return 0 if summary["healthy"] else 1
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
            state = ("retired" if r["retired_at"]
                     else "enabled" if r["enabled"] else "disabled")
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
            manual_url=args.url,
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
                  f"unchanged={run.get('unchanged', 0)} "
                  f"failed={run.get('failed', 0)})")
            for err in run.get("errors", []):
                print(f"  error: {err}")
    failed = sum(1 for r in summary["runs"] if r["status"] in ("failed", "partial"))
    return 1 if failed else 0


def cmd_watch(args: argparse.Namespace) -> int:
    from lawradar.db.lock import LockBusy
    from lawradar.ingestion.watch import run_watch

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    logger = get_logger("lawradar.watch")

    def _report(result) -> None:
        if args.json:
            return  # dumped once, at the end
        for source_id, run in zip(result.ingested, result.runs):
            print(f"[sweep {result.sweep}] {source_id}: {run['status']} "
                  f"(unchanged={run.get('unchanged', 0)} "
                  f"changed={run.get('changed', 0)} "
                  f"failed={run.get('failed', 0)})")
            for err in run.get("errors", []):
                print(f"  error: {err}")
        for source_id, reason in result.skipped.items():
            print(f"[sweep {result.sweep}] {source_id}: skipped ({reason})")

    if not args.once:
        print("Watching enabled sources on their poll schedule "
              "(Ctrl-C to stop). manual_import sources always need "
              "an explicit `lawradar ingest <id> --file …`.")
    try:
        results = run_watch(
            config,
            getattr(args, "sources_file", None) or None,
            limit=args.limit,
            poll_seconds=args.poll_seconds,
            max_sweeps=1 if args.once else args.max_sweeps,
            on_sweep=_report,
        )
    except KeyboardInterrupt:
        print("watch interrupted; finished cleanly")
        return 0
    except LockBusy as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    # A failed sweep is fatal only in --once mode (schedulers retry);
    # the loop keeps going because one bad source must not stop the rest.
    failed = any(result.failed for result in results)
    if args.once and failed:
        logger.error("watch sweep had failed/partial runs")
        return 1
    return 0


def cmd_documents(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.ingestion.pipeline import _db_path

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    store.init_db(_db_path(config))
    conn = store.connect(_db_path(config))
    try:
        if args.documents_command == "list":
            rows = store.list_documents(
                conn, args.limit, source=args.source,
                doc_type=args.type, jurisdiction=args.jurisdiction)
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
                validated = doc["http_validated_at"] or "(never)"
                if validated != "(never)":
                    etag = doc["http_etag"] or "(none)"
                    last_mod = doc["http_last_modified"] or "(none)"
                    print(f"  last validated={validated} etag={etag[:24]} "
                          f"last_modified={last_mod[:24]}")
                for v in versions:
                    print(f"  v{v['version_number']} sha={v['content_sha256'][:12]}… "
                          f"extraction={v['extraction_status']} "
                          f"review={v['review_status']} retrieved={v['retrieved_at']}")
        elif args.documents_command == "search":
            from lawradar.search import fts as search_fts

            search_fts.ensure_indexed(conn)
            rows = search_fts.search(
                conn, args.query, args.limit, source=args.source,
                doc_type=args.type, jurisdiction=args.jurisdiction)
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for r in rows:
                    print(f"[{r['id']}] {r['title']} ({r['engine']})")
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
            since = None
            if args.since:
                from datetime import datetime as _dt

                try:
                    day = _dt.strptime(args.since, "%Y-%m-%d")
                except ValueError:
                    print("--since must be YYYY-MM-DD (UTC)", file=sys.stderr)
                    return 2
                since = day.strftime("%Y-%m-%dT00:00:00.000Z")
            if (args.change_type or args.verification or since):
                rows = store.list_reports_filtered(
                    conn, document_id=args.document, limit=args.limit,
                    change_type=args.change_type,
                    verification=args.verification, since=since)
            else:
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
        elif args.reports_command == "brief":
            from lawradar.ingestion.health import format_utc, utc_now
            from lawradar.reporting.brief import (
                BriefError,
                BriefRefused,
                build_brief,
            )

            try:
                text = build_brief(conn, args.report_id,
                                   generated_at=format_utc(utc_now()))
            except BriefRefused as exc:
                print(f"brief refused: {exc}", file=sys.stderr)
                return 2
            except BriefError as exc:
                print(f"brief failed: {exc}", file=sys.stderr)
                return 1
            payload_bytes = len(text.encode("utf-8"))
            if args.json:
                print(json.dumps({"report_id": args.report_id,
                                  "bytes": payload_bytes,
                                  "out": args.out or "",
                                  "markdown": text}, indent=2))
                return 0
            if args.out:
                path = Path(args.out)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                print(f"wrote {path} ({payload_bytes} bytes)")
            else:
                print(text, end="")
            return 0
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
        if outcome["decision"] == "approved":
            # Fire-and-forget: committed publication is never rolled back,
            # and delivery failures are recorded, not raised.
            from lawradar.notify.dispatch import after_approval

            outcome["notifications"] = after_approval(
                config, conn, args.report_id)
        trail = audit_trail(conn, args.report_id)
        if args.json:
            print(json.dumps({**outcome, "audit_trail": trail}, indent=2,
                             default=str))
        else:
            print(f"report {outcome['report_id']}: {outcome['decision']} "
                  f"by {outcome['reviewer']} "
                  f"(tasks resolved: {outcome['tasks_resolved']})")
            print(f"  audit trail entries: {len(trail)}")
            notifications = outcome.get("notifications") or []
            if notifications:
                counts: dict[str, int] = {}
                for item in notifications:
                    counts[item.get("status", "?")] = \
                        counts.get(item.get("status", "?"), 0) + 1
                summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
                print(f"  notifications: {summary}"
                      f" (`lawradar notify send` retries failed targets)")
        return 0
    finally:
        conn.close()


def cmd_serve(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.db.lock import LockBusy
    from lawradar.ingestion.pipeline import _db_path
    from lawradar.web.server import serve_forever

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    store.init_db(_db_path(config))
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.token:
        print("Refusing to bind a non-loopback address without --token: "
              "review POSTs would be unprotected. Set --token or use a "
              "reverse proxy with authentication.", file=sys.stderr)
        return 2
    try:
        serve_forever(str(_db_path(config)), host=args.host, port=args.port,
                      token=args.token,
                      post_limit_per_minute=config.post_limit_per_minute,
                      config=config)
    except LockBusy as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from lawradar.evaluation.runner import run

    setup_logging(getattr(args, "log_level", None) or "INFO", "")
    result = run()
    if args.json:
        print(json.dumps({"metrics": result.metrics, "cases": result.cases},
                         indent=2))
    else:
        print("Pilot evaluation (bounded fixture set — see SCOPE)")
        print(f"  cases: {result.metrics['cases_passed']}/"
              f"{result.metrics['cases']} passed")
        print(f"  change recall:      {result.metrics['change_recall']:.0%}")
        print(f"  citation correctness: {result.metrics['citation_correctness']:.0%}")
        print(f"  status errors:      {result.metrics['status_errors']}")
        print(f"  failed runs visible: {result.metrics['failed_runs_visible']}")
        for case in result.cases:
            print(f"  [{'PASS' if case['pass'] else 'FAIL'}] {case['case']}")
        print("These numbers do NOT generalise beyond the curated set.")
    return 0 if result.metrics["cases_passed"] == result.metrics["cases"] else 1


def cmd_feedback(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.ingestion.pipeline import _db_path

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    store.init_db(_db_path(config))
    conn = store.connect(_db_path(config))
    try:
        if args.feedback_command == "list":
            rows = store.list_feedback(conn, args.status, args.limit)
            if args.json:
                print(json.dumps([dict(r) for r in rows], indent=2,
                                 default=str))
            else:
                for row in rows:
                    print(f"[{row['id']}] report={row['change_report_id']} "
                          f"status={row['status']} "
                          f"{row['message'][:120]}")
                if not rows:
                    print("No feedback yet.")
        elif args.feedback_command == "resolve":
            try:
                store.resolve_feedback(conn, args.feedback_id)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            conn.commit()
            print(f"feedback {args.feedback_id} resolved")
    finally:
        conn.close()
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.ingestion.pipeline import _db_path
    from lawradar.notify.dispatch import (
        NotifyError,
        dispatch_pending,
        targets_from_config,
    )

    config = _effective_config(args)
    setup_logging(config.log_level, config.log_file)
    store.init_db(_db_path(config))
    conn = store.connect(_db_path(config))
    try:
        if args.notify_command == "list":
            rows = store.list_notification_attempts(
                conn, change_report_id=args.report,
                status=args.status, limit=args.limit)
            if args.json:
                print(json.dumps([dict(r) for r in rows], indent=2,
                                 default=str))
            else:
                if getattr(config, "notify_enabled", False):
                    print("notify: enabled")
                else:
                    print("notify: disabled (notifications are off)")
                try:
                    targets = targets_from_config(config)
                except NotifyError as exc:
                    targets = []
                    print(f"  target config error: {exc}")
                if targets:
                    for t in targets:
                        print(f"  target: {t.name} -> {t.url} "
                              f"({'on' if t.enabled else 'off'}"
                              f"{', signed' if t.secret else ''})")
                elif not getattr(config, "notify_enabled", False):
                    print("  (no targets configured; see "
                          "config/settings.example.yaml)")
                else:
                    print("  (no targets configured)")
                if not rows:
                    print("No delivery attempts yet.")
                for r in rows:
                    http = (f" http={r['http_status']}"
                            if r["http_status"] is not None else "")
                    error = (f" error={r['error'][:120]}"
                             if r["error"] else "")
                    print(f"[{r['id']}] report={r['change_report_id']} "
                          f"webhook={r['webhook']} {r['status']}{http}"
                          f" at {r['created_at']}{error}")
            return 0
        # send
        if not getattr(config, "notify_enabled", False):
            print("notify: disabled; set notify_enabled: true in settings "
                  "and add notify_webhooks targets", file=sys.stderr)
            return 2
        try:
            outcomes = dispatch_pending(
                conn, config, report_id=args.report, limit=args.limit)
        except NotifyError as exc:
            print(f"notify send failed: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(outcomes, indent=2))
        else:
            if not outcomes:
                print("Nothing outstanding — every published report has "
                      "been delivered to its pending targets.")
            for item in outcomes:
                line = f"report {args.report or '?'} {item['webhook']}: " \
                       f"{item['status']}"
                if item.get("http_status") is not None:
                    line += f" (HTTP {item['http_status']})"
                if item.get("error"):
                    line += f" {item['error'][:160]}"
                print(line)
        failed = sum(1 for item in outcomes if item.get("status") == "failed")
        return 1 if failed else 0
    finally:
        conn.close()


def cmd_backup(args: argparse.Namespace) -> int:
    from lawradar.db.backup import (
        BackupError,
        create_backup,
        restore_backup,
        verify_backup,
    )
    from lawradar.ingestion.pipeline import _db_path

    try:
        if args.backup_command == "verify":
            info = verify_backup(args.backup_path)
            if args.json:
                print(json.dumps(info.to_dict(), indent=2))
            else:
                print(f"backup: OK {info.name}")
                print(f"  sha256: {info.sha256}")
                print(f"  created_at: {info.created_at}")
                print(f"  manifest: {'yes' if info.has_manifest else 'no'}")
                print("  counts: " + ", ".join(
                    f"{key}={value}" for key, value in info.counts.items()))
            return 0
        config = _effective_config(args)
        setup_logging(config.log_level, config.log_file)
        db_path = _db_path(config)
        if args.backup_command == "create":
            if args.keep < 0:
                print("--keep must be >= 0", file=sys.stderr)
                return 2
            out_dir = args.out or (db_path.parent / "backups")
            info = create_backup(db_path, out_dir, keep=args.keep)
            if args.json:
                print(json.dumps(info.to_dict(), indent=2))
            else:
                print(f"backup: {info.path}")
                print(f"  sha256: {info.sha256}")
                print(f"  bytes: {info.bytes}")
                print("  counts: " + ", ".join(
                    f"{key}={value}" for key, value in info.counts.items()))
                if args.keep:
                    print(f"  retention: kept {args.keep} most recent")
            return 0
        result = restore_backup(
            args.backup_path, db_path,
            force=args.force,
            safety_dir=db_path.parent / "backups")
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"restored: {result['target']}")
            print(f"  from: {result['restored_from']}")
            print(f"  sha256: {result['sha256']}")
            if result["safety_backup"]:
                label = ("safety backup (unverified)"
                         if "-unverified-" in Path(result["safety_backup"]).name
                         else "safety backup")
                print(f"  {label}: {result['safety_backup']}")
            print("  counts: " + ", ".join(
                f"{key}={value}" for key, value in result["counts"].items()))
        return 0
    except (BackupError, OSError, sqlite3.Error) as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1


def cmd_bundles(args: argparse.Namespace) -> int:
    from lawradar.db import store
    from lawradar.evidence.bundle import (
        BundleError,
        BundleRefused,
        create_bundle,
        verify_bundle,
    )
    from lawradar.ingestion.pipeline import _db_path

    try:
        if args.bundles_command == "verify":
            info = verify_bundle(args.bundle_path)
            if args.json:
                print(json.dumps(info.to_dict(), indent=2))
            else:
                print(f"bundle: OK {Path(info.path).name}")
                print(f"  report_id: {info.report_id}")
                print(f"  document: "
                      f"{'included' if info.has_document else 'absent'}")
                if info.has_document:
                    print(f"  document_sha256: {info.document_sha256}")
                print(f"  exported_at: {info.created_at}")
                print(f"  bundle_sha256: {info.sha256}")
            return 0
        config = _effective_config(args)
        setup_logging(config.log_level, config.log_file)
        db_path = _db_path(config)
        store.init_db(db_path)
        conn = store.connect(db_path)
        try:
            if args.bundles_command == "create":
                info = create_bundle(
                    conn, args.report_id, args.out,
                    data_dir=Path(config.data_dir))
                if args.json:
                    print(json.dumps(info.to_dict(), indent=2))
                else:
                    print(f"bundle: {info.path}")
                    print(f"  report_id: {info.report_id}")
                    print(f"  document: "
                          f"{'included' if info.has_document else 'absent'}")
                    if info.has_document:
                        print(f"  document_sha256: {info.document_sha256}")
                    print(f"  bytes: {info.bytes}")
                    print(f"  bundle_sha256: {info.sha256}")
                return 0
            rows = store.list_evidence_bundles(
                conn, args.report, limit=args.limit)
            if args.json:
                print(json.dumps([dict(r) for r in rows], indent=2,
                                 default=str))
            else:
                if not rows:
                    print("No bundles exported yet. Try `lawradar bundles "
                          "create <report-id>`.")
                for row in rows:
                    doc = "doc included" if row["has_document"] else "no doc"
                    print(f"[{row['id']}] report={row['change_report_id']} "
                          f"{row['name']} ({doc}) "
                          f"sha256={row['sha256'][:12]} "
                          f"at={row['created_at']}")
            return 0
        finally:
            conn.close()
    except BundleRefused as exc:
        print(f"bundle refused: {exc}", file=sys.stderr)
        return 2
    except (BundleError, OSError, sqlite3.Error) as exc:
        print(f"bundle failed: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "health":
        return cmd_health(args)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "sources":
        return cmd_sources(args)
    if args.command == "ingest":
        return cmd_ingest(args)
    if args.command == "watch":
        return cmd_watch(args)
    if args.command == "documents":
        return cmd_documents(args)
    if args.command == "reports":
        return cmd_reports(args)
    if args.command == "review":
        return cmd_review(args)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "eval":
        return cmd_eval(args)
    if args.command == "feedback":
        return cmd_feedback(args)
    if args.command == "notify":
        return cmd_notify(args)
    if args.command == "backup":
        return cmd_backup(args)
    if args.command == "bundles":
        return cmd_bundles(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
