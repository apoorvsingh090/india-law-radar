"""Source health unit tests (Milestone 9): deterministic classification."""
from datetime import UTC, datetime, timedelta

from lawradar.ingestion.health import (
    evaluate_source,
    evaluate_sources,
    parse_utc,
    stale_after_minutes,
    summarize,
    with_health,
)

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=UTC)


def _ts(minutes_ago: float) -> str:
    moment = NOW - timedelta(minutes=minutes_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _row(**overrides) -> dict:
    row = {
        "id": "fx",
        "name": "FX",
        "enabled": 1,
        "access_method": "fixture",
        "poll_interval_minutes": 60,
        "created_at": _ts(10),
        "last_checked_at": None,
        "last_success_at": None,
        "last_error": None,
    }
    row.update(overrides)
    return row


def test_disabled_and_manual_are_not_monitored():
    disabled = evaluate_source(_row(enabled=0, last_error="old failure"), NOW)
    assert disabled.status == "disabled"
    assert disabled.healthy and not disabled.monitored
    manual = evaluate_source(_row(access_method="manual_import"), NOW)
    assert manual.status == "manual"
    assert manual.healthy and not manual.monitored
    assert "ingest fx --file" in manual.detail


def test_never_checked_is_due_when_fresh_but_stale_when_old():
    fresh = evaluate_source(_row(created_at=_ts(5)), NOW)
    assert fresh.status == "due" and fresh.healthy
    old = evaluate_source(_row(created_at=_ts(300)), NOW)
    assert old.status == "stale" and not old.healthy


def test_ok_and_next_due():
    row = _row(last_checked_at=_ts(10), last_success_at=_ts(10))
    health = evaluate_source(row, NOW)
    assert health.status == "ok" and health.healthy
    assert health.next_due_at == "2026-10-26T12:50:00Z"
    assert health.stale_after_minutes == 120


def test_due_inside_staleness_window_is_not_unhealthy():
    health = evaluate_source(
        _row(last_checked_at=_ts(61), last_success_at=_ts(61)), NOW)
    assert health.status == "due" and health.healthy


def test_stale_after_one_missed_sweep_window():
    health = evaluate_source(
        _row(last_checked_at=_ts(121), last_success_at=_ts(121)), NOW)
    assert health.status == "stale" and not health.healthy


def test_stale_boundary_is_inclusive():
    health = evaluate_source(
        _row(last_checked_at=_ts(120), last_success_at=_ts(120)), NOW)
    assert health.status == "stale"


def test_last_error_beats_recent_success_and_is_unhealthy():
    health = evaluate_source(
        _row(last_checked_at=_ts(5), last_success_at=_ts(5),
             last_error="HTTP 403 from source"), NOW)
    assert health.status == "failing" and not health.healthy
    assert "HTTP 403" in health.detail


def test_stale_threshold_has_a_floor():
    assert stale_after_minutes(1) == 15
    assert stale_after_minutes(1440) == 2880


def test_parse_utc_tolerates_naive_and_garbage():
    assert parse_utc("2026-10-26T12:00:00") == NOW
    assert parse_utc("2026-10-26T12:00:00Z") == NOW
    assert parse_utc("not-a-date") is None
    assert parse_utc(None) is None


def test_summary_and_merge_helpers():
    rows = [
        _row(id="a", last_checked_at=_ts(10), last_success_at=_ts(10)),
        _row(id="b", last_checked_at=_ts(121), last_success_at=_ts(121)),
        _row(id="m", access_method="manual_import"),
        _row(id="d", enabled=0),
    ]
    items = evaluate_sources(rows, NOW)
    summary = summarize(items, NOW)
    assert summary["healthy"] is False
    assert summary["monitored"] == 2
    assert summary["unhealthy"] == 1
    assert summary["stale"] == 1 and summary["failing"] == 0
    assert [s["source_id"] for s in summary["sources"]] == ["a", "b", "m", "d"]
    merged = with_health(rows, NOW)
    assert merged[0]["status"] == "ok"
    assert merged[0]["id"] == "a" and merged[0]["health_detail"]
    assert parse_utc(merged[0]["last_success_at"]) is not None
