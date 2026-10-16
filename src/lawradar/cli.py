"""Command-line interface for India Law Radar (Milestone 1).

Implemented commands (all functional, no placeholders):
  lawradar init    — create data dir, local settings.yaml, empty sqlite db marker
  lawradar health  — verify config loads, data dir writable, sqlite works

Future milestones will add: sources, ingest, documents, reports, review.
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

    # Touch an empty sqlite db so later milestones have a stable path.
    db_path = _sqlite_path(config.db_url, data_dir)
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS _meta (k TEXT PRIMARY KEY, v TEXT)")
            conn.execute(
                "INSERT OR IGNORE INTO _meta (k, v) VALUES ('schema_version', 'm1')"
            )
            conn.commit()
        finally:
            conn.close()
        logger.info("sqlite ready: %s", db_path)

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


APP_LABEL = "India Law Radar v0.1.0 (Milestone 1)"


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
                row = conn.execute(
                    "SELECT v FROM _meta WHERE k='schema_version'"
                ).fetchone()
                checks["sqlite"] = {
                    "ok": True,
                    "detail": f"{db_path} (schema_version={row[0] if row else '?'})",
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args)
    if args.command == "health":
        return cmd_health(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
