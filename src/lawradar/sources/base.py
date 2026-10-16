"""Base class contract for source adapters (Milestone 2+).

Every adapter must declare: source id, display name, base URL, document
types, jurisdiction, retrieval method, poll interval, rate limit,
coverage limits, storage/redistribution status, health + last error.
No network code in M1.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SourceAdapter:
    """Minimal declared contract (fetch logic arrives in M2)."""

    source_id: str
    name: str
    base_url: str
    jurisdiction: str = "unknown"
    enabled: bool = False
    coverage_notes: str = ""
