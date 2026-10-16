"""Base class contract for source adapters (Milestone 2).

Every adapter must declare: source id, display name, base URL, document
types, jurisdiction, retrieval method, poll interval, rate limit,
coverage limits, storage/redistribution status, health + last error.
Runtime state (last check/success/error) lives in the DB ``sources``
table; static declarations live in ``config/sources.yaml`` and are
validated by ``lawradar.sources.registry``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SourceAdapter:
    """Minimal declared contract (fetch logic per adapter)."""

    source_id: str
    name: str
    base_url: str
    jurisdiction: str = "unknown"
    document_types: tuple[str, ...] = ()
    access_method: str = "manual_import"
    poll_interval_minutes: int = 1440
    rate_limit_seconds: float = 1.0
    enabled: bool = False
    storage_policy: str = "unknown"
    coverage_notes: str = ""
