"""Watch loop unit tests (Milestone 8): due computation + sweeps."""
from datetime import datetime, timedelta, timezone

import yaml

from lawradar.config import load_settings
from lawradar.ingestion.watch import (
    is_due,
    parse_utc,
    run_sweep,
    run_watch,
)
from lawradar.sources.registry import _validate

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

FIXTURE = {
    "id": "fx", "name": "FX", "base_url": "https://example.invalid/fx/",
    "access_method": "fixture", "enabled": True, "rate_limit_seconds": 0,
    "poll_interval_minutes": 1440, "storage_policy": "allowed",
    "terms_review_status": "reviewed_ok",
}
MANUAL = {
    "id": "m", "name": "M", "base_url": "https://indiacode.gov.in/",
    "access_method": "manual_import", "enabled": True,
    "rate_limit_seconds": 0, "poll_interval_minutes": 10080,
}


def _source(**overrides):
    entry = {**FIXTURE, **overrides}
    return _validate(entry)


def test_parse_utc_roundtrip():
    parsed = parse_utc("2026-10-23T11:00:00.123Z")
    assert parsed == datetime(2026, 10, 23, 11, 0, 0, 123000,
                              tzinfo=timezone.utc)
    assert parse_utc("") is None
    assert parse_utc(None) is None
    assert parse_utc("garbage") is None


def test_due_when_never_checked():
    due, reason = is_due(_source(), None, NOW)
    assert due and reason == ""


def test_not_due_inside_interval():
    stamp = (NOW - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    due, reason = is_due(_source(), stamp, NOW)
    assert not due and "not due until" in reason


def test_due_after_interval():
    stamp = (NOW - timedelta(minutes=1441)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    due, _ = is_due(_source(), stamp, NOW)
    assert due


def test_daily_cron_starting_seconds_early_is_still_due():
    stamp = (NOW - timedelta(minutes=1440) + timedelta(seconds=5)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    due, _ = is_due(_source(), stamp, NOW)
    assert due


def test_manual_and_disabled_never_due():
    due, reason = is_due(_source(access_method="manual_import"), None, NOW)
    assert not due and "operator file" in reason
    due, reason = is_due(_source(enabled=False), None, NOW)
    assert not due and "disabled" in reason


def _setup(tmp_path, monkeypatch, sources):
    monkeypatch.chdir(tmp_path)
    for var in ("LAWRADAR_CONFIG", "LAWRADAR_DATA_DIR", "LAWRADAR_DB_URL",
                "LAWRADAR_LOG_LEVEL", "LAWRADAR_LOG_FILE"):
        monkeypatch.delenv(var, raising=False)
    config = load_settings()
    config.data_dir = str(tmp_path / "data")
    config.db_url = f"sqlite:///{tmp_path / 'data' / 'lawradar.db'}"
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump({"sources": sources}), encoding="utf-8")
    return config, str(path)


def test_sweep_ingests_then_respects_interval(tmp_path, monkeypatch):
    config, sources_file = _setup(tmp_path, monkeypatch,
                                  [FIXTURE, MANUAL])
    # Anchor to the real wall clock: ingest_source stamps last_checked_at
    # with SQLite 'now', so the injected clock must track real time.
    base = datetime.now(timezone.utc)
    first = run_sweep(config, sources_file, now=base)
    assert first.ingested == ["fx"]
    assert first.changed == 2  # two bundled fixture documents
    assert first.skipped["m"].startswith("manual_import")
    # Seconds later: fixture just checked, manual still manual.
    second = run_sweep(config, sources_file, now=base + timedelta(seconds=5))
    assert second.ingested == [] and second.runs == []
    assert "not due until" in second.skipped["fx"]
    # A day later the fixture is due again — and dedups (changed=0).
    later = base + timedelta(minutes=1441)
    third = run_sweep(config, sources_file, now=later)
    assert third.ingested == ["fx"]
    assert third.changed == 0
    assert all(run["status"] == "success" for run in third.runs)


def test_transient_db_error_does_not_kill_sweep(tmp_path, monkeypatch):
    import sqlite3

    config, sources_file = _setup(tmp_path, monkeypatch, [FIXTURE])

    def _boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("lawradar.ingestion.watch.ingest_source", _boom)
    result = run_sweep(config, sources_file,
                       now=datetime.now(timezone.utc))
    assert result.ingested == ["fx"]
    assert result.failed == 1
    assert result.runs[0]["errors"] == ["database is locked"]


def test_run_watch_loop_injectable_sleep(tmp_path, monkeypatch):
    config, sources_file = _setup(tmp_path, monkeypatch, [FIXTURE])
    sleeps: list[float] = []
    base = datetime.now(timezone.utc)

    def fake_now():
        return base  # fixed: sweep 0 ingests, sweeps 1-2 see "not due"

    results = run_watch(config, sources_file, max_sweeps=3,
                        poll_seconds=42.0, sleep=sleeps.append,
                        now_fn=fake_now)
    assert len(results) == 3
    assert sleeps == [42.0, 42.0]  # no sleep after the final sweep
    assert [r.sweep for r in results] == [0, 1, 2]
    # Only the first sweep ingests; the next two see "not due".
    assert results[0].ingested == ["fx"]
    assert results[1].ingested == [] and results[2].ingested == []


def test_run_watch_stop_event(tmp_path, monkeypatch):
    import threading

    config, sources_file = _setup(tmp_path, monkeypatch, [FIXTURE])
    stop = threading.Event()

    def sleep_until_stopped(seconds):
        stop.set()

    results = run_watch(config, sources_file, sleep=sleep_until_stopped,
                        stop=stop)
    assert len(results) == 1
