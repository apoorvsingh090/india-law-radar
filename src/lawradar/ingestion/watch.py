"""Watch mode (Milestone 8): the radar sweep loop.

``lawradar watch`` polls enabled sources on their ``poll_interval_minutes``
schedule. Each sweep ingests every source whose last recorded check is
older than its interval, reusing the idempotent ingestion pipeline
(identical bytes never create a duplicate version; a failed run never
marks a source successfully checked). manual_import sources are never
swept automatically — they need an operator-supplied ``--file`` — and are
reported as skipped with a reason, mirroring the project's humans-close-
the-loop review policy.

Deterministic and testable: the clock, the sleeper, and a stop event are
injectable, so tests exercise the loop without real waiting.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from lawradar.db import store
from lawradar.ingestion.pipeline import _db_path, ingest_source, sync_registry
from lawradar.sources.registry import SourceRecord, load_sources

EPOCH_STAMP = "1970-01-01T00:00:00.000Z"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(text: str | None) -> datetime | None:
    """Parse the store's ``%Y-%m-%dT%H:%M:%fZ`` stamps; None when absent."""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_due(source: SourceRecord, last_checked: str | None,
           now: datetime) -> tuple[bool, str]:
    """Return (due, skip_reason). skip_reason is empty when due."""
    if not source.enabled:
        return False, "disabled in registry"
    if source.access_method == "manual_import":
        return False, ("manual_import: needs an operator file — run "
                       "`lawradar ingest <id> --file PATH`")
    last = parse_utc(last_checked)
    interval = timedelta(minutes=max(1, source.poll_interval_minutes))
    if last is None:
        return True, ""
    if now >= last + interval:
        return True, ""
    due_at = (last + interval).strftime("%Y-%m-%dT%H:%M:%SZ")
    return False, (f"not due until {due_at} "
                   f"(interval {source.poll_interval_minutes}m)")


@dataclass
class SweepResult:
    sweep: int
    ingested: list[str] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    changed: int = 0

    @property
    def failed(self) -> int:
        return sum(1 for run in self.runs
                   if run.get("status") in ("failed", "partial"))

    def to_dict(self) -> dict:
        return {"sweep": self.sweep, "ingested": list(self.ingested),
                "runs": self.runs, "skipped": dict(self.skipped),
                "changed": self.changed, "failed_runs": self.failed}


def run_sweep(config, sources_file: str | None = None, *, limit: int = 100,
              now: datetime | None = None) -> SweepResult:
    """Ingest every enabled, due source once. Never raises per-source."""
    moment = now if now is not None else utc_now()
    db_path = _db_path(config)
    store.init_db(db_path)
    conn = store.connect(db_path)
    try:
        sources = load_sources(sources_file)
        sync_registry(conn, sources)
        last_checked = {row["id"]: (row["last_checked_at"] or "")
                        for row in store.list_sources(conn)}
        result = SweepResult(sweep=0)
        for source in sources:
            due, reason = is_due(source, last_checked.get(source.id, ""),
                                 moment)
            if not due:
                result.skipped[source.id] = reason
                continue
            run = ingest_source(conn, config, source, limit=limit)
            result.ingested.append(source.id)
            result.runs.append(run)
        result.changed = sum(run.get("changed", 0) for run in result.runs)
        return result
    finally:
        conn.close()


def run_watch(config, sources_file: str | None = None, *, limit: int = 100,
              poll_seconds: float = 300.0, max_sweeps: int | None = None,
              sleep=time.sleep, now_fn=None, stop=None,
              on_sweep=None) -> list[SweepResult]:
    """Sweep immediately, then every ``poll_seconds`` until stopped.

    Stops after ``max_sweeps`` sweeps or when ``stop`` is set; returns all
    sweep results. ``sleep``/``now_fn``/``stop`` are injection points for
    tests and embedding.
    """
    clock = now_fn if now_fn is not None else utc_now
    results: list[SweepResult] = []
    sweeps = 0
    while True:
        if stop is not None and stop.is_set():
            return results
        result = run_sweep(config, sources_file, limit=limit, now=clock())
        result.sweep = sweeps
        results.append(result)
        if on_sweep is not None:
            on_sweep(result)
        sweeps += 1
        if max_sweeps is not None and sweeps >= max_sweeps:
            return results
        sleep(poll_seconds)
