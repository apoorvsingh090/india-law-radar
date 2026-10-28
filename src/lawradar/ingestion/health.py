"""Source health evaluation (Milestone 9).

Answers the question the watch loop cannot: is each *monitored* source
actually succeeding on its own schedule? Health is derived only from
timestamps the pipeline already records - no network calls, no guesses.

Statuses
--------
``disabled``  registry entry is off; never affects overall health
``manual``    manual_import; a human supplies the file, not a sweep
``ok``        last sweep succeeded and the next one is not due yet
``due``       a sweep is due (or the first one is pending); not a failure
``stale``     no successful check within the staleness threshold
``failing``   the most recent check failed (``last_error`` is set)

A source is stale after ``max(15, 2 * poll_interval)`` minutes without a
success. That tolerates one missed sweep at every interval but catches a
loop that silently stopped running. Only enabled automated sources count
toward ``healthy``; disabled/manual sources are reported, never alerted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

AUTOMATED_METHODS = frozenset({"fixture", "http_poll"})
STALE_FACTOR = 2
MIN_STALE_MINUTES = 15
MAX_DETAIL_CHARS = 300


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_utc(text: str | None) -> datetime | None:
    """Parse the store's ``%Y-%m-%dT%H:%M:%fZ`` stamps; None when absent."""
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return (moment.replace(tzinfo=UTC) if moment.tzinfo is None
            else moment.astimezone(UTC))


def format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stale_after_minutes(poll_interval_minutes: int) -> int:
    interval = max(1, int(poll_interval_minutes or 1))
    return max(MIN_STALE_MINUTES, STALE_FACTOR * interval)


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    name: str
    status: str
    healthy: bool
    monitored: bool
    detail: str
    next_due_at: str
    stale_after_minutes: int
    last_checked_at: str
    last_success_at: str
    last_error: str

    def to_dict(self) -> dict:
        return asdict(self)


def _text(value) -> str:
    return "" if value is None else str(value)


def _field(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _interval(row) -> int:
    try:
        return max(1, int(row["poll_interval_minutes"] or 1))
    except (TypeError, ValueError):
        return 1440


def evaluate_source(row, now: datetime | None = None) -> SourceHealth:
    """Classify one source row (dict or sqlite3.Row). Pure and total."""
    moment = now if now is not None else utc_now()
    interval = _interval(row)
    stale_after = stale_after_minutes(interval)
    last_checked = parse_utc(row["last_checked_at"])
    last_success = parse_utc(row["last_success_at"])
    created = parse_utc(row["created_at"])
    last_error = _text(row["last_error"]).strip()
    due_at = (last_checked + timedelta(minutes=interval)
              if last_checked is not None else None)
    next_due = format_utc(due_at) if due_at is not None else ""

    def _make(status: str, healthy: bool, monitored: bool, detail: str
              ) -> SourceHealth:
        return SourceHealth(
            source_id=_text(row["id"]),
            name=_text(row["name"]),
            status=status,
            healthy=healthy,
            monitored=monitored,
            detail=detail[:MAX_DETAIL_CHARS],
            next_due_at=next_due,
            stale_after_minutes=stale_after,
            last_checked_at=_text(row["last_checked_at"]),
            last_success_at=_text(row["last_success_at"]),
            last_error=last_error[:MAX_DETAIL_CHARS],
        )

    if _text(_field(row, "retired_at")).strip():
        return _make("retired", True, False,
                     "removed from the source registry; history retained")
    if not bool(row["enabled"]):
        return _make("disabled", True, False, "disabled in registry")
    if _text(row["access_method"]) not in AUTOMATED_METHODS:
        return _make("manual", True, False,
                     f"manual import only - run `lawradar ingest {row['id']} "
                     "--file PATH`")

    if last_error:
        return _make("failing", False, True,
                     f"last check failed: {last_error}")

    if last_success is None:
        if created is None:
            # A missing/invalid registration time must not disable the
            # never-successful alarm by making the source look brand new.
            return _make(
                "stale", False, True,
                f"never succeeded and registration time is invalid "
                f"({_text(row['created_at']) or 'missing'}; "
                f"threshold {stale_after}m)")
        age_minutes = (moment - created).total_seconds() / 60
        if age_minutes >= stale_after:
            return _make(
                "stale", False, True,
                f"never succeeded since registration "
                f"({_text(row['created_at']) or 'unknown'}; "
                f"threshold {stale_after}m)")
        return _make("due", True, True,
                     "never checked; first sweep pending")

    age_minutes = (moment - last_success).total_seconds() / 60
    if age_minutes >= stale_after:
        return _make(
            "stale", False, True,
            f"no successful check for {int(age_minutes)}m "
            f"(threshold {stale_after}m)")
    if due_at is None or moment >= due_at:
        return _make("due", True, True, "due on next sweep")
    return _make("ok", True, True, "last sweep succeeded")


def evaluate_sources(rows, now: datetime | None = None) -> list[SourceHealth]:
    return [evaluate_source(row, now) for row in rows]


def with_health(rows, now: datetime | None = None) -> list[dict]:
    """Merge health fields into source rows for pages/JSON consumers."""
    merged: list[dict] = []
    for row, health in zip(rows, evaluate_sources(rows, now), strict=False):
        item = dict(row)
        item.update({
            "status": health.status,
            "healthy": health.healthy,
            "monitored": health.monitored,
            "health_detail": health.detail,
            "next_due_at": health.next_due_at,
            "stale_after_minutes": health.stale_after_minutes,
        })
        merged.append(item)
    return merged


def summarize(items: list[SourceHealth],
              now: datetime | None = None) -> dict:
    moment = now if now is not None else utc_now()
    unhealthy = [item for item in items if not item.healthy]
    return {
        "checked_at": format_utc(moment),
        "healthy": not unhealthy,
        "monitored": sum(1 for item in items if item.monitored),
        "unhealthy": len(unhealthy),
        "stale": sum(1 for item in items if item.status == "stale"),
        "failing": sum(1 for item in items if item.status == "failing"),
        "sources": [item.to_dict() for item in items],
    }
