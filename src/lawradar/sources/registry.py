"""Source registry: load + validate the official-source catalogue.

Source of truth order: ``config/sources.yaml`` (local, git-ignored) →
``config/sources.example.yaml`` (shipped). Every adapter must declare the
fields required by spec section 4; invalid entries are rejected loudly,
never silently skipped.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

ACCESS_METHODS = {"manual_import", "fixture", "http_poll"}
STORAGE_POLICIES = {"allowed", "unknown", "restricted"}
TERMS_STATUSES = {"not_reviewed", "reviewed_ok", "reviewed_restricted"}


@dataclass
class SourceRecord:
    id: str
    name: str
    base_url: str
    source_type: str = "unknown"
    jurisdiction: str = "unknown"
    access_method: str = "manual_import"
    terms_review_status: str = "not_reviewed"
    poll_interval_minutes: int = 1440
    rate_limit_seconds: float = 1.0
    enabled: bool = False
    coverage_notes: str = ""
    storage_policy: str = "unknown"
    last_checked_at: str = ""
    last_success_at: str = ""
    last_error: str = ""

    def host(self) -> str:
        return (urllib.parse.urlparse(self.base_url).hostname or "").lower()


def _validate(entry: dict) -> SourceRecord:
    if not isinstance(entry, dict):
        raise ValueError("each source entry must be a mapping")
    source_id = str(entry.get("id", "")).strip()
    if not source_id or not all(
        ch.islower() or ch.isdigit() or ch in "-_" for ch in source_id
    ):
        raise ValueError(f"invalid source id: {source_id!r} (lowercase slug required)")
    base_url = str(entry.get("base_url", "")).strip()
    parts = urllib.parse.urlparse(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"source {source_id}: base_url must be http(s) with host")
    access_method = str(entry.get("access_method", "manual_import")).strip()
    if access_method not in ACCESS_METHODS:
        raise ValueError(
            f"source {source_id}: unknown access_method {access_method!r} "
            f"(expected one of {sorted(ACCESS_METHODS)})"
        )
    storage_policy = str(entry.get("storage_policy", "unknown")).strip()
    if storage_policy not in STORAGE_POLICIES:
        raise ValueError(f"source {source_id}: unknown storage_policy {storage_policy!r}")
    terms = str(entry.get("terms_review_status", "not_reviewed")).strip()
    if terms not in TERMS_STATUSES:
        raise ValueError(f"source {source_id}: unknown terms_review_status {terms!r}")
    try:
        poll = int(entry.get("poll_interval_minutes", 1440))
        rate = float(entry.get("rate_limit_seconds", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"source {source_id}: bad interval/rate: {exc}") from exc
    return SourceRecord(
        id=source_id,
        name=str(entry.get("name", source_id)),
        base_url=base_url,
        source_type=str(entry.get("source_type", "unknown")),
        jurisdiction=str(entry.get("jurisdiction", "unknown")),
        access_method=access_method,
        terms_review_status=terms,
        poll_interval_minutes=poll,
        rate_limit_seconds=rate,
        enabled=bool(entry.get("enabled", False)),
        coverage_notes=str(entry.get("coverage_notes", "")),
        storage_policy=storage_policy,
    )


def find_sources_file(explicit: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path("config/sources.yaml"))
    candidates.append(Path("config/sources.example.yaml"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_sources(explicit: str | None = None) -> list[SourceRecord]:
    """Load and validate all sources. Raises on any invalid entry."""
    if yaml is None:
        raise RuntimeError("pyyaml is required to load the source registry")
    path = find_sources_file(explicit)
    if path is None:
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    entries = data.get("sources", []) if isinstance(data, dict) else []
    if not isinstance(entries, list):
        raise ValueError(f"{path}: 'sources' must be a list")
    records = [_validate(entry) for entry in entries]
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            raise ValueError(f"duplicate source id: {record.id}")
        seen.add(record.id)
    return records


def allowed_hosts(sources: list[SourceRecord]) -> set[str]:
    """Hosts that the fetcher may contact (enabled http_poll sources)."""
    return {
        source.host()
        for source in sources
        if source.access_method == "http_poll" and source.host()
    }
